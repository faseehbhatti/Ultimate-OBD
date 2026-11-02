"""Tkinter GUI for the OBD-II reader.

Pages: Connect / Engine / ABS / I/M / TPMS, with a session-log dock.
Workers never call Tk — they enqueue callables drained by the UI-thread pump.

Run from the project root:  py src/gui.py  (or  py src/gui.py --demo)
"""

from __future__ import annotations

import collections
import ctypes
import queue
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from features.obd_client import OBDClient, list_serial_ports, to_float
from features.vehicle_db import BRANDS, brand_info
from ui.theme import (ACCENT, ACCENT_RICH, ACCENT_WASH, AMBER, BG, BORDER,
                      DANGER_TEXT, DISPLAY_FONT, FAINT, FIELD, GREEN,
                      HEADLINE_FONT, INK, LIVE, LIVE_PALE, LIVE_TEXT, MONO,
                      MUTED, MUTE_DEEP, RED, SIDEBAR, STATUS_COLORS, SURFACE,
                      SURFACE_2, TEXT, TYPE, WORDMARK_FONT, apply_theme,
                      divider, label, mono_font, seam, tag)
from ui.widgets import (Card, Gauge, Mark, NavItem, PageStack, ScrollArea,
                        StatusDot, Toggle, Tracked, TrendChart, fill_tree,
                        style_tree)


def micro(parent, text: str, *, bg: str = SURFACE, fg: str = FAINT,
          tracking: float = 2.2, weight: str = "bold") -> Tracked:
    """Tracked mono micro label — the system's label voice."""
    return Tracked(parent, text, size=TYPE["micro"], weight=weight, family=MONO,
                   fg=fg, bg=bg, tracking=tracking)


def eyebrow(parent, text: str, *, bg: str = SURFACE,
            fg: str = MUTED) -> Tracked:
    """Small mono eyebrow above a title (tracking 0.18em)."""
    return Tracked(parent, text.upper(), size=TYPE["micro"], weight="normal",
                   family=MONO, fg=fg, bg=bg, tracking=2.0)


def _enable_dpi_awareness() -> None:
    """Render at real pixels instead of letting Windows bitmap-scale the app."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


class App(tk.Tk):
    def __init__(self, demo_default=False):
        super().__init__()
        self.title("Ultimate OBD — Diagnostics")
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(1280, max(1000, screen_w - 80))
        height = min(920, max(680, screen_h - 100))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(1180, width), min(720, height))

        self.client = OBDClient(demo=demo_default)
        self._mon_stop: threading.Event | None = None
        self._samples = 0
        self._last_t = 0.0
        self._q: queue.Queue = queue.Queue()      # worker -> UI (samples)
        self._calls: queue.Queue = queue.Queue()  # worker -> UI (callables)
        self._polling = False
        self._connected = False
        self.history: dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=90))
        self.nav_items: dict[tk.Widget, NavItem] = {}

        apply_theme(self)
        self._build_shell()
        self._build_connect_tab()
        self._build_obd_tab()
        self._build_abs_tab()
        self._build_im_tab()
        self._build_tpms_tab()
        self._build_nav()
        self._select_page(self.tab_connect)
        self.refresh_ports()
        self._refresh_vehicle()
        self._refresh_demo_badge()
        self._light_titlebar()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.after(100, self._pump_calls)

    def _light_titlebar(self) -> None:
        """Match the Windows chrome to the paper ground (best effort)."""
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            off = ctypes.c_int(0)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(off), ctypes.sizeof(off))
            caption = ctypes.c_int(0x00FFFFFF)  # COLORREF white
            text = ctypes.c_int(0x00000000)     # COLORREF black
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
        except Exception:
            pass

    # ================= shell =================
    def _build_shell(self):
        """Sidebar + header + page stack + log pane. Pages are added later."""
        self.side = tk.Frame(self, bg=SIDEBAR, width=256)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        tk.Frame(self.side, bg=BORDER, width=1).pack(side="right", fill="y")
        self._build_sidebar()

        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=BG, padx=28, pady=20)
        header.pack(fill="x")
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        self.eyebrow_var = tk.StringVar(value="01 / CONNECT")
        self.eyebrow = Tracked(titles, "01 / CONNECT", size=TYPE["micro"],
                               weight="normal", family=MONO, fg=ACCENT,
                               bg=BG, tracking=2.2)
        self.eyebrow.pack(anchor="w", pady=(0, 4))
        self.page_title_var = tk.StringVar(value="Connect")
        self.page_sub_var = tk.StringVar(value="")
        label(titles, "", size=TYPE["headline"], bg=BG, fg=INK,
              family=HEADLINE_FONT,
              textvariable=self.page_title_var).pack(anchor="w")
        label(titles, "", size=TYPE["small"], fg=MUTED, bg=BG,
              textvariable=self.page_sub_var).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header, bg=BG)
        right.pack(side="right")
        self.demo_badge = tag(right, "DEMO MODE", kind="accent")
        pill = tk.Frame(right, bg=SURFACE_2, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        pill.pack(side="right")
        self.conn_dot = StatusDot(pill, bg=SURFACE_2)
        self.conn_dot.pack(side="left", padx=(12, 7), pady=8)
        self.conn_label = tk.Label(pill, text="Disconnected",
                                   font=mono_font(TYPE["micro"], "bold"),
                                   fg=DANGER_TEXT, bg=SURFACE_2,
                                   padx=0, pady=7, bd=0, highlightthickness=0)
        self.conn_label.pack(side="left", padx=(0, 13))

        rule = tk.Frame(main, bg=BG, padx=28)
        rule.pack(fill="x")
        seam(rule, width=64).pack(side="left")
        divider(rule).pack(side="left", fill="x", expand=True)

        self.pw = tk.PanedWindow(main, orient="vertical", bg=BG, sashwidth=8,
                                 bd=0, sashrelief="flat")
        self.pw.pack(fill="both", expand=True, padx=20, pady=(12, 16))
        self.stack = PageStack(self.pw, on_select=self._on_page_change)
        self.pw.add(self.stack, minsize=420, stretch="always")
        self._build_log_panel()

    def _build_sidebar(self):
        brand = tk.Frame(self.side, bg=SIDEBAR, padx=22, pady=22)
        brand.pack(fill="x")
        Mark(brand, size=28, bg=SIDEBAR).pack(side="left")
        names = tk.Frame(brand, bg=SIDEBAR)
        names.pack(side="left", padx=(12, 0))
        Tracked(names, "ULTIMATE OBD", size=TYPE["wordmark"], weight="normal",
                family=WORDMARK_FONT, fg=INK, bg=SIDEBAR,
                tracking=2.6).pack(anchor="w")

        self.nav_area = tk.Frame(self.side, bg=SIDEBAR)
        self.nav_area.pack(fill="x")

        card = Card(self.side, padding=14, seam=True)
        card.pack(side="bottom", fill="x", padx=14, pady=16)
        micro(card.body, "VEHICLE").pack(fill="x")
        self.side_vehicle_var = tk.StringVar(value="No vehicle detected")
        self.side_vin_var = tk.StringVar(value="VIN —")
        self.side_proto_var = tk.StringVar(value="Protocol —")
        label(card.body, "", size=TYPE["small"], weight="bold", fg=INK,
              bg=SURFACE, textvariable=self.side_vehicle_var,
              wraplength=196).pack(fill="x", pady=(5, 4))
        label(card.body, "", size=TYPE["micro"], fg=MUTED, bg=SURFACE,
              family=MONO, textvariable=self.side_vin_var,
              wraplength=196).pack(fill="x")
        label(card.body, "", size=10, fg=FAINT, bg=SURFACE,
              textvariable=self.side_proto_var,
              wraplength=196).pack(fill="x", pady=(4, 0))

    def _build_nav(self):
        entries = [
            (self.tab_connect, "connect", "Connect"),
            (self.tab_obd, "engine", "Engine"),
            (self.tab_abs, "abs", "ABS"),
            (self.tab_im, "readiness", "I/M Readiness"),
            (self.tab_tpms, "tpms", "TPMS"),
        ]
        for page, icon, title in entries:
            item = NavItem(self.nav_area, icon, title,
                           lambda p=page: self._select_page(p))
            item.pack(fill="x")
            self.nav_items[page] = item

    def _build_log_panel(self):
        wrap = tk.Frame(self.pw, bg=BG)
        card = Card(wrap, padding=0)
        card.pack(fill="both", expand=True)
        head = tk.Frame(card.body, bg=SURFACE, padx=16, pady=9)
        head.pack(fill="x")
        micro(head, "SESSION LOG", fg=MUTED).pack(side="left")
        for text, command in (("Open folder", self.on_open_logs),
                              ("Save now", self.on_save_log),
                              ("Clear", self.on_clear_log)):
            ttk.Button(head, text=text, style="Small.TButton",
                       command=command).pack(side="right", padx=(6, 0))
        body = tk.Frame(card.body, bg=FIELD)
        body.pack(fill="both", expand=True)
        self.log = tk.Text(body, bg=FIELD, fg=MUTED, insertbackground=ACCENT,
                           selectbackground=ACCENT_WASH, selectforeground=INK,
                           relief="flat", bd=0, highlightthickness=0,
                           wrap="word", font=mono_font(TYPE["mono_lg"]),
                           padx=16, pady=10, height=6)
        self.log.tag_configure("err", foreground=DANGER_TEXT)
        self.log.tag_configure("ok", foreground=LIVE_TEXT)
        self.log.tag_configure("dim", foreground=FAINT)
        scroll = ttk.Scrollbar(body, orient="vertical",
                               command=self.log.yview,
                               style="Slim.Vertical.TScrollbar")
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.pw.add(wrap, minsize=96, height=150, stretch="never")
        self.log.insert("end", "Log — saves to logs/ on exit.\n\n", "dim")
        self.log.see("1.0")

    # ================= navigation / header =================
    def _page(self, title: str, subtitle: str = ""):
        """Create a scrollable page; returns (stack host, grid body)."""
        host = ScrollArea(self.stack, bg=BG)
        self.stack.add(host, title, subtitle)
        return host, host.body

    def _select_page(self, page: tk.Widget):
        self.stack.select(page)

    def _on_wheel(self, event):
        """Route the wheel to the visible page when its content overflows."""
        host = self.stack.select()
        if not isinstance(host, ScrollArea) or not host.scrollable:
            return
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not host:
            widget = widget.master
        if widget is None:
            return
        step = -1 if event.delta > 0 else 1
        host.canvas.yview_scroll(step * 3, "units")

    def _on_page_change(self, page: tk.Widget, title: str, subtitle: str):
        self.page_title_var.set(title)
        self.page_sub_var.set(subtitle)
        pages = list(self.nav_items)
        index = pages.index(page) + 1 if page in pages else 0
        self.eyebrow.set(f"{index:02d} / {title.upper()}")
        for candidate, item in self.nav_items.items():
            item.set_active(candidate is page)

    def _refresh_demo_badge(self):
        if self.demo_var.get():
            self.demo_badge.pack(side="right", padx=(0, 10))
        else:
            self.demo_badge.pack_forget()

    def _on_demo_toggle(self):
        self._refresh_demo_badge()

    # ================= helpers =================
    def refresh_ports(self):
        ports = list_serial_ports()
        self.port_box["values"] = ["Auto"] + ports
        if not self.port_var.get():
            self.port_var.set("Auto")
        self.write(f"Ports: {', '.join(ports) if ports else '(none found)'} "
                   f"(pick Auto, a listed port, or type one like COM4)\n")

    def selected_port(self) -> str | None:
        """None = Auto-detect; otherwise the manually set port string."""
        pick = self.port_var.get().strip()
        if not pick or pick.lower() == "auto":
            return None
        return pick

    def write(self, s: str):
        # Thread-safe: UI thread writes now, workers enqueue for the pump.
        self.call_ui(lambda: self._write(s))

    def _write(self, s: str):
        if "FAILED" in s or "FAIL" in s:
            self.log.insert("end", s, "err")
        elif "saved" in s.lower() or "Connected" in s or "clear sent" in s.lower():
            self.log.insert("end", s, "ok")
        else:
            self.log.insert("end", s)
        self.log.see("end")

    def _set_conn_label(self, text: str, color: str):
        def apply():
            hue = STATUS_COLORS.get(color, TEXT)
            self.conn_label.config(text=text, fg=hue)
            self.conn_dot.set(hue, glow=(color == "green"))
        self.call_ui(apply)

    def _show_features(self):
        """Jump to the Engine page after a successful connection."""
        self.call_ui(lambda: self.stack.select(self.tab_obd))

    # ================= Connect page =================
    def _build_connect_tab(self):
        host, page = self._page("Connect")
        self.tab_connect = host
        page.grid_columnconfigure(0, weight=2)
        page.grid_columnconfigure(1, weight=3)
        page.grid_rowconfigure(1, weight=1)

        ready = Card(page, padding=18, seam=True)
        ready.grid(row=0, column=0, columnspan=2, sticky="ew")
        rrow = tk.Frame(ready.body, bg=SURFACE)
        rrow.pack(fill="x")
        micro(rrow, "READY TO SCAN", fg=ACCENT, tracking=2.4).pack(side="left")
        label(rrow, "Ignition ON · engine running for live data",
              size=TYPE["small"], fg=MUTED, bg=SURFACE).pack(side="right")

        # -- connection settings ------------------------------------------
        settings = Card(page, padding=18)
        settings.grid(row=1, column=0, sticky="nsew", pady=(12, 0), padx=(0, 6))
        micro(settings.body, "CONNECTION").pack(fill="x", pady=(0, 12))

        form = tk.Frame(settings.body, bg=SURFACE)
        form.pack(fill="x")
        form.grid_columnconfigure(1, weight=1)
        micro(form, "COM PORT", fg=FAINT, tracking=1.8, weight="normal").grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        self.port_var = tk.StringVar()
        port_row = tk.Frame(form, bg=SURFACE)
        port_row.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))
        self.port_box = ttk.Combobox(port_row, textvariable=self.port_var, width=10)
        self.port_box.pack(side="left", fill="x", expand=True)
        ttk.Button(port_row, text="Refresh", style="Small.TButton",
                   command=self.refresh_ports).pack(side="left", padx=(6, 0))

        micro(form, "BAUD RATE", fg=FAINT, tracking=1.8, weight="normal").grid(
            row=2, column=0, sticky="w", pady=(0, 2))
        self.baud_var = tk.StringVar(value="auto")
        ttk.Combobox(form, textvariable=self.baud_var, width=12,
                     values=["auto", "38400", "9600", "115200", "230400"]).grid(
                         row=3, column=1, sticky="w", padx=(12, 0))

        self.demo_var = tk.BooleanVar(value=self.client.demo)
        Toggle(settings.body, "Demo mode",
               self.demo_var, command=self._on_demo_toggle).pack(
                   anchor="w", pady=(18, 0))
        divider(settings.body).pack(fill="x", pady=16)
        ttk.Button(settings.body, text="Connect & detect vehicle",
                   style="Accent.TButton", command=self.on_connect_detect).pack(
                       fill="x")

        # -- vehicle identity ---------------------------------------------
        identity = Card(page, padding=18)
        identity.grid(row=1, column=1, sticky="nsew", pady=(12, 0), padx=(6, 0))
        micro(identity.body, "VEHICLE IDENTITY").pack(fill="x", pady=(0, 12))

        self.home_vars = {}
        micro(identity.body, "VIN", fg=FAINT, tracking=1.8,
              weight="normal").pack(fill="x")
        self.home_vars["vin"] = tk.StringVar(value="--")
        label(identity.body, "", size=TYPE["body"], fg=INK, bg=SURFACE,
              family=MONO, textvariable=self.home_vars["vin"],
              wraplength=470).pack(fill="x", pady=(3, 12))

        pairs = tk.Frame(identity.body, bg=SURFACE)
        pairs.pack(fill="x", pady=(0, 12))
        for index, (key, title) in enumerate((("conn", "STATUS"),
                                              ("profile", "PROFILE"))):
            cell = tk.Frame(pairs, bg=SURFACE)
            cell.grid(row=0, column=index, sticky="w",
                      padx=(0, 28 if index == 0 else 0))
            pairs.grid_columnconfigure(index, weight=1, uniform="pair")
            micro(cell, title, fg=FAINT, tracking=1.8,
                  weight="normal").pack(fill="x")
            var = tk.StringVar(value="--")
            self.home_vars[key] = var
            label(cell, "", size=TYPE["small"], fg=MUTED, bg=SURFACE,
                  textvariable=var).pack(fill="x", pady=(2, 0))

        micro(identity.body, "ABS PATH", fg=FAINT, tracking=1.8,
              weight="normal").pack(fill="x")
        self.home_vars["abs"] = tk.StringVar(value="--")
        label(identity.body, "", size=TYPE["small"], fg=MUTED, bg=SURFACE,
              textvariable=self.home_vars["abs"], wraplength=470).pack(
                  fill="x", pady=(3, 10))

        divider(identity.body).pack(fill="x", pady=(0, 12))
        micro(identity.body, "IDENTIFY THE CAR").pack(fill="x", pady=(0, 6))
        picker = tk.Frame(identity.body, bg=SURFACE)
        picker.pack(fill="x")
        for col, text in enumerate(("MAKE", "YEAR", "MODEL")):
            micro(picker, text, fg=FAINT, tracking=1.8,
                  weight="normal").grid(row=0, column=col, sticky="w",
                                        padx=(0, 8), pady=(0, 3))
        self.make_var = tk.StringVar(value="")
        self.make_box = ttk.Combobox(picker, textvariable=self.make_var,
                                     width=12, state="readonly",
                                     values=sorted(BRANDS))
        self.make_box.grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.make_box.bind("<<ComboboxSelected>>", lambda _e: self.on_make_pick())
        self.year_var = tk.StringVar(value="")
        ttk.Entry(picker, textvariable=self.year_var, width=5).grid(
            row=1, column=1, sticky="w", padx=(0, 8))
        self.model_var = tk.StringVar(value="")
        self.model_box = ttk.Combobox(picker, textvariable=self.model_var,
                                      width=12, state="readonly")
        self.model_box.grid(row=1, column=2, sticky="w", padx=(0, 8))
        self.model_box.bind("<<ComboboxSelected>>", lambda _e: self.on_model_pick())
        ttk.Button(picker, text="Set", style="Small.TButton",
                   command=self.on_manual_vehicle).grid(row=1, column=3, sticky="w")

    # ================= Engine page =================
    def _build_obd_tab(self):
        host, page = self._page("Engine")
        self.tab_obd = host
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=3)
        page.grid_rowconfigure(3, weight=2)

        toolbar = Card(page, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")
        bar = tk.Frame(toolbar.body, bg=SURFACE)
        bar.pack(fill="x")
        actions = [
            ("Read codes", "Accent.TButton", self.on_read),
            ("Clear codes", "Danger.TButton", self.on_clear),
            ("Mode 06", "Ghost.TButton", self.on_mode06),
            ("Freeze frame", "Ghost.TButton", self.on_freeze),
            ("ECU info", "Ghost.TButton", self.on_ecuinfo),
            ("Health report", "Ghost.TButton", self.on_health),
        ]
        for text, style, command in actions:
            ttk.Button(bar, text=text, style=style, command=command).pack(
                side="left", padx=(0, 6))
        self.dtc_status = label(bar, "", size=TYPE["micro"], fg=MUTED,
                                bg=SURFACE, family=MONO)
        self.dtc_status.pack(side="right", padx=(12, 4))

        gauges = tk.Frame(page, bg=BG)
        gauges.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tiles = (
            ("Engine RPM", "rpm", 0, 6000, ACCENT, "g_rpm"),
            ("Vehicle speed", "km/h", 0, 200, LIVE, "g_spd"),
            ("Coolant", "°C", 50, 120, ACCENT_RICH, "g_clt"),
            ("Engine load", "%", 0, 100, LIVE_TEXT, "g_ld"),
        )
        for col, (title, unit, vmin, vmax, color, attr) in enumerate(tiles):
            gauges.grid_columnconfigure(col, weight=1, uniform="gauges")
            gauge = Gauge(gauges, title, unit, vmin, vmax, bar_color=color)
            gauge.grid(row=0, column=col, sticky="nsew",
                       padx=(0 if col == 0 else 4, 0 if col == 3 else 4))
            setattr(self, attr, gauge)

        charts = tk.Frame(page, bg=BG)
        charts.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        charts.grid_rowconfigure(0, weight=1)
        charts.grid_columnconfigure(0, weight=3)
        charts.grid_columnconfigure(1, weight=2)
        self.chart_drive = TrendChart(
            charts, "Engine speed vs vehicle speed",
            [("RPM (rpm)", "RPM", ACCENT), ("Speed (km/h)", "Speed", LIVE)],
            vmin=0, vmax=6000, height=112)
        self.chart_drive.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.chart_fuel = TrendChart(
            charts, "Fuel trims — bank 1",
            [("STFT B1 (%)", "STFT", LIVE_PALE),
             ("LTFT B1 (%)", "LTFT", ACCENT_RICH)],
            vmin=-10, vmax=10, height=96)
        self.chart_fuel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        tables = tk.Frame(page, bg=BG)
        tables.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        tables.grid_rowconfigure(0, weight=1)
        tables.grid_columnconfigure(0, weight=3)
        tables.grid_columnconfigure(1, weight=2)

        codes = Card(tables, padding=14)
        codes.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        micro(codes.body, "FAULT CODES").pack(fill="x", pady=(0, 8))
        self.dtc_tree = self._tree(codes.body, "Code", "Description",
                                   (100, 380), 3)
        self.dtc_tree.pack(fill="both", expand=True)

        live = Card(tables, padding=14)
        live.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        micro(live.body, "LIVE PIDS").pack(fill="x", pady=(0, 8))
        self.mon_tree = self._tree(live.body, "PID", "Value", (180, 100), 3)
        self.mon_tree.pack(fill="both", expand=True)

        controls = Card(page, padding=10)
        controls.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        cbar = tk.Frame(controls.body, bg=SURFACE)
        cbar.pack(fill="x")
        micro(cbar, "REALTIME").pack(side="left", padx=(2, 12))
        label(cbar, "Interval (s)", size=TYPE["micro"], fg=MUTED, bg=SURFACE,
              family=MONO).pack(side="left")
        self.interval_var = tk.StringVar(value="0.5")
        ttk.Spinbox(cbar, textvariable=self.interval_var, from_=0.3, to=10,
                    increment=0.5, width=5).pack(side="left", padx=(6, 16))
        label(cbar, "CSV log", size=TYPE["micro"], fg=MUTED, bg=SURFACE,
              family=MONO).pack(side="left")
        self.csv_var = tk.StringVar(value="")
        ttk.Entry(cbar, textvariable=self.csv_var, width=14).pack(
            side="left", padx=(6, 6))
        ttk.Button(cbar, text="Browse", style="Small.TButton",
                   command=self.on_browse_csv).pack(side="left")
        self.btn_dash = ttk.Button(cbar, text="▶  Start realtime",
                                   style="Accent.TButton",
                                   command=self.on_monitor_toggle)
        self.btn_dash.pack(side="right")
        self.dash_status = label(cbar, "Stopped", size=TYPE["micro"], fg=MUTED,
                                 bg=SURFACE, family=MONO)
        self.dash_status.pack(side="right", padx=(0, 14))

    # ================= ABS page =================
    def _build_abs_tab(self):
        host, page = self._page("ABS")
        self.tab_abs = host
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        info = Card(page, padding=16, seam=True)
        info.grid(row=0, column=0, sticky="ew")
        micro(info.body, "SKID CONTROL ECU", fg=ACCENT).pack(fill="x")

        actions = Card(page, padding=10)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        abar = tk.Frame(actions.body, bg=SURFACE)
        abar.pack(fill="x")
        ttk.Button(abar, text="Read ABS codes", style="Accent.TButton",
                   command=self.on_abs_read).pack(side="left", padx=(0, 6))
        ttk.Button(abar, text="Probe module", style="Ghost.TButton",
                   command=self.on_abs_probe).pack(side="left", padx=(0, 6))
        ttk.Button(abar, text="Clear ABS codes", style="Danger.TButton",
                   command=self.on_abs_clear).pack(side="left")
        self.abs_status = label(abar, "", size=TYPE["micro"], fg=MUTED,
                                bg=SURFACE, family=MONO)
        self.abs_status.pack(side="right", padx=(12, 4))

        split = tk.Frame(page, bg=BG)
        split.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        split.grid_rowconfigure(0, weight=1)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)

        codes = Card(split, padding=14)
        codes.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        micro(codes.body, "ABS CODES").pack(fill="x", pady=(0, 8))
        self.abs_tree = self._tree(codes.body, "Code", "Description",
                                   (90, 340), 8)
        self.abs_tree.pack(fill="both", expand=True)

        right = tk.Frame(split, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        guide = Card(right, padding=16)
        guide.grid(row=0, column=0, sticky="ew")
        micro(guide.body, "PROBE RESULTS").pack(fill="x", pady=(0, 8))
        for text, color, body in (
                ("DATA", LIVE, "Module answered."),
                ("REJECTION", ACCENT_RICH, "Refused — try another header."),
                ("SILENCE", DANGER_TEXT, "No reply — check header or protocol.")):
            row = tk.Frame(guide.body, bg=SURFACE)
            row.pack(fill="x", pady=2)
            label(row, text, size=TYPE["micro"], weight="bold", fg=color,
                  bg=SURFACE, family=MONO, width=10).pack(side="left", anchor="n")
            label(row, body, size=TYPE["micro"], fg=MUTED, bg=SURFACE,
                  wraplength=280).pack(side="left", fill="x", expand=True)

        advanced = Card(right, padding=14)
        advanced.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        micro(advanced.body, "RAW QUERY · HEADER + COMMAND").pack(
            fill="x", pady=(0, 8))
        fields = tk.Frame(advanced.body, bg=SURFACE)
        fields.pack(fill="x")
        micro(fields, "HEADER", fg=FAINT, tracking=1.8,
              weight="normal").grid(row=0, column=0, sticky="w")
        self.abs_hdr_var = tk.StringVar(value="")
        ttk.Entry(fields, textvariable=self.abs_hdr_var, width=7).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(3, 0))
        micro(fields, "COMMAND", fg=FAINT, tracking=1.8,
              weight="normal").grid(row=0, column=1, sticky="w")
        self.abs_cmd_var = tk.StringVar(value="19 02 FF")
        ttk.Entry(fields, textvariable=self.abs_cmd_var, width=14).grid(
            row=1, column=1, sticky="w", padx=(0, 8), pady=(3, 0))
        ttk.Button(fields, text="Send", style="Ghost.TButton",
                   command=self.on_abs_raw).grid(row=1, column=2, sticky="w",
                                                 pady=(3, 0))

    # ================= I/M page =================
    def _build_im_tab(self):
        host, page = self._page("I/M Readiness")
        self.tab_im = host
        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=2)
        page.grid_rowconfigure(1, weight=1)

        banner = Card(page, padding=20, seam=True)
        banner.grid(row=0, column=0, columnspan=2, sticky="ew")
        micro(banner.body, "EMISSIONS READINESS", fg=ACCENT).pack(fill="x")
        brow = tk.Frame(banner.body, bg=SURFACE)
        brow.pack(fill="x", pady=(4, 0))
        self.im_status = label(brow, "Not checked yet", size=TYPE["display"],
                               fg=INK, bg=SURFACE,
                               family=DISPLAY_FONT)
        self.im_status.pack(side="left")
        ttk.Button(brow, text="Refresh readiness", style="Accent.TButton",
                   command=self.on_im).pack(side="right")

        monitors = Card(page, padding=14)
        monitors.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 5))
        micro(monitors.body, "MONITORS").pack(fill="x", pady=(0, 8))
        self.im_tree = self._tree(monitors.body, "Monitor", "Status",
                                  (280, 200), 10)
        self.im_tree.pack(fill="both", expand=True)

        meaning = Card(page, padding=20)
        meaning.grid(row=1, column=1, sticky="nsew", pady=(10, 0), padx=(5, 0))
        micro(meaning.body, "LEGEND").pack(fill="x", pady=(0, 12))
        for color, title, text in (
                (LIVE, "Complete", "Tested since the last clear."),
                (ACCENT_RICH, "Incomplete", "Not enough drive time."),
                (MUTE_DEEP, "N/A", "Not fitted.")):
            label(meaning.body, title, size=TYPE["small"], weight="bold", fg=color,
                  bg=SURFACE).pack(fill="x")
            label(meaning.body, text, size=TYPE["micro"], fg=MUTED, bg=SURFACE,
                  wraplength=300).pack(fill="x", pady=(2, 12))

    # ================= TPMS page =================
    def _build_tpms_tab(self):
        host, page = self._page("TPMS")
        self.tab_tpms = host
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        info = Card(page, padding=16, seam=True)
        info.grid(row=0, column=0, sticky="ew")
        irow = tk.Frame(info.body, bg=SURFACE)
        irow.pack(fill="x")
        micro(irow, "TIRE PRESSURE MONITORING", fg=ACCENT).pack(side="left")
        label(irow, "Live pressures need a documented PID.",
              size=TYPE["small"], fg=MUTED, bg=SURFACE).pack(side="right")

        actions = Card(page, padding=10)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        abar = tk.Frame(actions.body, bg=SURFACE)
        abar.pack(fill="x")
        ttk.Button(abar, text="Read TPMS codes", style="Accent.TButton",
                   command=self.on_tpms_read).pack(side="left", padx=(0, 6))
        ttk.Button(abar, text="Live pressures", style="Ghost.TButton",
                   command=self.on_tpms_live).pack(side="left")
        self.tpms_status = label(abar, "", size=TYPE["micro"], fg=MUTED,
                                 bg=SURFACE, family=MONO)
        self.tpms_status.pack(side="right", padx=(12, 4))

        tiles = tk.Frame(page, bg=BG)
        tiles.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.tpms_gauges = {}
        corners = (("FL (psi)", "FRONT LEFT"), ("FR (psi)", "FRONT RIGHT"),
                   ("RL (psi)", "REAR LEFT"), ("RR (psi)", "REAR RIGHT"))
        for col, (key, title) in enumerate(corners):
            tiles.grid_columnconfigure(col, weight=1, uniform="tires")
            tile = Card(tiles, padding=14)
            tile.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 4, 0 if col == 3 else 4))
            micro(tile.body, title, fg=FAINT, tracking=2.0).pack(fill="x")
            row = tk.Frame(tile.body, bg=SURFACE)
            row.pack(fill="x", pady=(3, 0))
            var = tk.StringVar(value="--")
            self.tpms_gauges[key] = var
            label(row, "", size=TYPE["display"], bg=SURFACE, fg=INK,
                  family=DISPLAY_FONT,
                  textvariable=var).pack(side="left")
            label(row, "psi", size=TYPE["micro"], fg=FAINT, bg=SURFACE,
                  family=MONO).pack(side="left", padx=(6, 0), pady=(0, 8),
                                     anchor="s")

        split = tk.Frame(page, bg=BG)
        split.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        split.grid_rowconfigure(0, weight=1)
        for col, weight in ((0, 3), (1, 2), (2, 2)):
            split.grid_columnconfigure(col, weight=weight)

        codes = Card(split, padding=14)
        codes.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        micro(codes.body, "TPMS CODES").pack(fill="x", pady=(0, 8))
        self.tpms_tree = self._tree(codes.body, "Code", "Description",
                                    (80, 200), 6)
        self.tpms_tree.pack(fill="both", expand=True)

        register = Card(split, padding=14)
        register.grid(row=0, column=1, sticky="nsew", padx=5)
        micro(register.body, "SENSOR IDS").pack(fill="x")
        label(register.body, "7–8 hex digits · verified preset required.",
              size=TYPE["micro"], fg=MUTED, bg=SURFACE, wraplength=230).pack(
                  fill="x", pady=(4, 10))
        self.tpms_id_vars = {}
        id_grid = tk.Frame(register.body, bg=SURFACE)
        id_grid.pack(fill="x")
        for index, corner in enumerate(("FL", "FR", "RL", "RR")):
            row, col = divmod(index, 2)
            cell = tk.Frame(id_grid, bg=SURFACE)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=3)
            micro(cell, corner, fg=FAINT, tracking=1.6,
                  weight="normal").pack(side="left", padx=(0, 6))
            var = tk.StringVar(value="")
            self.tpms_id_vars[corner] = var
            ttk.Entry(cell, textvariable=var, width=9).pack(side="left")
        ttk.Button(register.body, text="Register IDs", style="Ghost.TButton",
                   command=self.on_tpms_register).pack(fill="x", pady=(12, 0))

        raw = Card(split, padding=14)
        raw.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        micro(raw.body, "RAW MODULE QUERY").pack(fill="x")
        label(raw.body, "Your model's PID, e.g. 22 F411.",
              size=TYPE["micro"], fg=MUTED, bg=SURFACE, wraplength=240).pack(
                  fill="x", pady=(4, 0))
        micro(raw.body, "HEADER", fg=FAINT, tracking=1.8,
              weight="normal").pack(fill="x", pady=(10, 3))
        self.tpms_hdr_var = tk.StringVar(value="")
        ttk.Entry(raw.body, textvariable=self.tpms_hdr_var,
                  width=8).pack(fill="x")
        micro(raw.body, "COMMAND", fg=FAINT, tracking=1.8,
              weight="normal").pack(fill="x", pady=(10, 3))
        self.tpms_cmd_var = tk.StringVar(value="22 ")
        ttk.Entry(raw.body, textvariable=self.tpms_cmd_var,
                  width=12).pack(fill="x")
        ttk.Button(raw.body, text="Send", style="Ghost.TButton",
                   command=self.on_tpms_raw).pack(fill="x", pady=(12, 0))

    # ================= shared builders =================
    def _tree(self, parent, first: str, second: str, widths: tuple[int, int],
              height: int) -> ttk.Treeview:
        """Two-column striped Treeview in the app's table style."""
        tree = ttk.Treeview(parent, columns=("c0",), show="tree headings",
                            height=height)
        tree.heading("#0", text=first, anchor="w")
        tree.heading("c0", text=second, anchor="w")
        tree.column("#0", width=widths[0], minwidth=60, stretch=False, anchor="w")
        tree.column("c0", width=widths[1], minwidth=80, stretch=True, anchor="w")
        style_tree(tree)
        return tree

    # ================= session logs =================
    @staticmethod
    def _slug(text: str | None, fallback: str = "Unknown") -> str:
        """Filesystem-safe name part: alphanumerics kept, runs of rest become '-'."""
        s = (text or "").strip() or fallback
        s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
        return s or fallback

    @staticmethod
    def _log_dir() -> Path:
        """Project-root logs/ dir (gui.py lives in src/, so root is one up).

        Frozen (PyInstaller) builds have no source tree: logs/ goes next
        to the .exe instead. __file__ inside a one-file bundle points at
        a temp dir, so sys.executable is used there.
        """
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            here = Path(__file__).resolve().parent
            root = here.parent if here.name == "src" else Path.cwd()
        d = root / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log_filename(self, when: datetime | None = None) -> str:
        """E.g. Honda_Civic_2007_20261001_143022.log (Unknown_* when unset)."""
        p = self.client.profile
        when = when or datetime.now()
        return (f"{self._slug(p.get('make'))}_{self._slug(p.get('model'), 'NoModel')}_"
                f"{p.get('year') or 'NoYear'}_{when:%Y%m%d_%H%M%S}.log")

    def save_log(self) -> Path | None:
        """Write the Log pane to logs/. Returns the path, or None on failure."""
        try:
            path = self._log_dir() / self.log_filename()
            header = (f"# OBD-II Reader session log\n# saved: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                      f"# VIN: {self.client.vin or '-'}\n"
                      f"# vehicle: {self.client.profile.get('make')} "
                      f"{self.client.profile.get('model') or ''} "
                      f"{self.client.profile.get('year') or ''}\n\n")
            path.write_text(header + self.log.get("1.0", "end-1c"), encoding="utf-8")
            return path
        except Exception as e:
            messagebox.showerror("Log save failed", f"Could not write session log:\n{e}")
            return None

    def on_save_log(self):
        saved = self.save_log()
        if saved is not None:
            self.write(f"Session log saved: {saved}\n")

    def on_clear_log(self):
        if messagebox.askyesno("Clear log", "Clear the on-screen session log?"):
            self.log.delete("1.0", "end")
            self.write("Log cleared.\n")

    def on_open_logs(self):
        """Open the session-log folder in the OS file manager."""
        try:
            import os
            folder = self._log_dir()
            if hasattr(os, "startfile"):
                os.startfile(folder)  # Windows
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showerror("Open logs failed", str(e))

    def _on_close(self):
        saved = self.save_log()
        if saved is not None:
            print(f"Session log saved: {saved}")
        try:
            if self._mon_stop is not None:
                self._mon_stop.set()
        finally:
            self.destroy()

    # ================= threading =================
    def run_bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def call_ui(self, fn):
        """Run fn on the UI thread: directly if already there, else via queue."""
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self._calls.put(fn)

    def _pump_calls(self):
        """UI-thread pump: run everything workers queued. Never dies."""
        try:
            while True:
                fn = self._calls.get_nowait()
                try:
                    fn()
                except Exception as e:
                    self._write(f"UI update failed: {e}\n")
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            if self.winfo_exists():
                self.after(100, self._pump_calls)
        except Exception:
            pass

    def on_browse_csv(self):
        f = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")])
        if f:
            self.csv_var.set(f)

    # ================= vehicle =================
    def _refresh_vehicle(self):
        p = self.client.profile
        self.home_vars["conn"].set("Connected" if self._connected else "Disconnected")
        self.home_vars["vin"].set(self.client.vin or "(unreadable)")
        self.home_vars["profile"].set(str(p.get("mode", "--")))
        self.home_vars["abs"].set(str(p.get("abs_mode", "--")))

        make = p.get("make") or "Unknown"
        model = p.get("model") or ""
        year = p.get("year") or ""
        identity = f"{year} {make} {model}".strip()
        self.side_vehicle_var.set(
            "No vehicle detected" if make == "Unknown" else identity)
        self.side_vin_var.set(f"VIN {self.client.vin}" if self.client.vin
                              else "VIN not read")
        self.side_proto_var.set(str(p.get("protocol") or "Protocol —"))

        self.make_box["values"] = sorted(BRANDS)
        cur_make = p.get("make") or ""
        self.make_var.set(cur_make if cur_make in BRANDS else "pick a make…")
        self.year_var.set(str(p.get("year") or ""))
        models = p.get("models", [])
        self.model_box["values"] = models
        cur = p.get("model") or ""
        self.model_var.set(cur if cur in models else ("pick a model…" if models else "--"))

    def on_make_pick(self):
        pick = self.make_var.get()
        if pick and not pick.endswith("…"):
            info = brand_info(pick)
            if info:
                self.model_box["values"] = info["models"]
                self.model_var.set("pick a model…")

    def on_manual_vehicle(self):
        make = self.make_var.get()
        if not make or make.endswith("…"):
            messagebox.showerror("Missing make", "Pick a make first.")
            return
        model = self.model_var.get()
        model = model if model and not model.endswith("…") and model != "--" else None
        year_txt = self.year_var.get().strip()
        year = None
        if year_txt:
            try:
                year = int(year_txt)
            except ValueError:
                messagebox.showerror("Bad year", f"'{year_txt}' is not a number.")
                return
        try:
            self.client.set_manual_vehicle(make, model=model, year=year)
        except ValueError as e:
            messagebox.showerror("Invalid vehicle", str(e))
            return
        self.write(f"\nVehicle set manually:\n{self.client.profile_summary()}\n")
        self._refresh_vehicle()

    def on_model_pick(self):
        pick = self.model_var.get()
        if pick and not pick.endswith("…"):
            self.client.set_model(pick)
            self.write(f"Model set: {pick} ({self.client.profile.get('make')})\n")
            self._refresh_vehicle()

    # ================= connect =================
    def on_connect_detect(self):
        def _do():
            if not self._connect_bg():
                return
            try:
                vin = self.client.read_vin()
                self.client.detect_compatibility(vin)
                self.write(f"\nVIN: {vin}\n{self.client.profile_summary()}\n")
            except Exception as e:
                self.write(f"VIN unreadable: {e}\n(Set make/model/year manually above.)\n")
                self.client.detect_compatibility(None)
            self.call_ui(self._refresh_vehicle)
            self._show_features()
        self.run_bg(_do)

    def _connect_bg(self) -> bool:
        """Shared connect routine (worker thread). Returns True on success."""
        try:
            self.client.demo = self.demo_var.get()
            port = self.selected_port()
            baud = None if self.baud_var.get() == "auto" else int(self.baud_var.get())
            if self.client.demo:
                msg = self.client.connect()
            else:
                self.write(f"Connecting on {port or 'Auto-detect'} ...\n")
                msg = self.client.connect(port=port, baudrate=baud)
            self.write(msg + "\n")
            self._connected = True
            self._set_conn_label("Connected", "green")
            self.call_ui(self._refresh_demo_badge)
            self.call_ui(self._refresh_vehicle)
            return True
        except Exception as e:
            self.write(f"CONNECT FAILED: {e}\n")
            self.call_ui(lambda: messagebox.showerror("Connect failed", str(e)))
            return False

    # ================= Engine: codes / reports =================
    def on_read(self):
        def _do():
            try:
                dtcs, info = self.client.read_dtcs()
                self.write(f"\nMIL: {info.get('mil')}  Count: {info.get('dtc_count')}\n")
                if info.get("pending"):
                    self.write(f"Pending: {', '.join(info['pending'])}\n")
                if info.get("permanent"):
                    self.write(f"Permanent: {', '.join(info['permanent'])}\n")
                if not dtcs:
                    self.write("No stored fault codes.\n")
                else:
                    for d in dtcs:
                        self.write(f"  {d.code} — {d.description}\n")
                self._update_dtc_tree(dtcs, info)
            except Exception as e:
                self.write(f"READ FAILED: {e}\n")
        self.run_bg(_do)

    def _update_dtc_tree(self, dtcs, info: dict):
        rows = [(d.code, (d.description,)) for d in dtcs]
        rows += [(f"{p} (pending)", ("unconfirmed — monitor",))
                 for p in info.get("pending", [])]
        status = f"MIL: {info.get('mil')}  ·  {info.get('dtc_count')} stored"
        color = RED if dtcs or info.get("mil") else GREEN
        self.call_ui(lambda: (fill_tree(self.dtc_tree, rows),
                               self.dtc_status.config(text=status, fg=color)))

    def on_mode06(self):
        def _do():
            try:
                self.write("\n" + self.client.format_mode06(self.client.read_mode06()) + "\n")
            except Exception as e:
                self.write(f"MODE 06 FAILED: {e}\n")
        self.run_bg(_do)

    def on_freeze(self):
        def _do():
            try:
                self.write("\n" + self.client.format_freeze(self.client.read_freeze_frame()) + "\n")
            except Exception as e:
                self.write(f"FREEZE FAILED: {e}\n")
        self.run_bg(_do)

    def on_ecuinfo(self):
        def _do():
            try:
                self.write("\n" + self.client.format_ecu_info(self.client.read_ecu_info()) + "\n")
            except Exception as e:
                self.write(f"ECU INFO FAILED: {e}\n")
        self.run_bg(_do)

    def on_health(self):
        def _do():
            try:
                from features.health_report import (gather_health, logs_dir,
                                                    report_filename, write_health_pdf)
                self.write("\nGathering health report (up to a minute)…\n")
                data = gather_health(self.client)
                self.write(f"  {data['verdict']}\n")
                path = write_health_pdf(data, logs_dir() / report_filename(self.client.profile))
                self.write(f"  Saved: {path}\n")
                self.call_ui(lambda: messagebox.showinfo(
                    "Health report", f"{data['verdict']}\nSaved:\n{path}"))
            except ImportError:
                self.write("\nHEALTH FAILED: pip install reportlab\n")
            except Exception as e:
                self.write(f"\nHEALTH FAILED: {e}\n")
        self.run_bg(_do)

    def on_clear(self):
        if not messagebox.askyesno("Confirm",
                "Clear all fault codes and turn off MIL?\nDo this only after noting/fixing the cause.\n"
                "Note: clearing resets I/M readiness to NOT READY."):
            return
        def _do():
            try:
                ok = self.client.clear_dtcs()
                self.write("Clear sent (Mode 04).\n" if ok else "Clear got no response.\n")
                self.on_read()
                self.on_im()
            except Exception as e:
                self.write(f"CLEAR FAILED: {e}\n")
        self.run_bg(_do)

    # ================= Engine: realtime =================
    def _push_sample(self, sample: dict):
        """Runs in the worker thread: only enqueue (never touch Tk here)."""
        now = time.time()
        dt = now - self._last_t if self._last_t else 0
        self._last_t = now
        self._samples += 1
        self._q.put((dict(sample), self._samples, dt))

    def _poll_queue(self):
        """Runs in the UI thread: drain queue and render."""
        try:
            while True:
                sample, n, dt = self._q.get_nowait()
                for k, v in sample.items():
                    f = to_float(v)
                    if f is not None:
                        self.history[k].append(f)
                self._render_realtime(sample, n, dt)
        except queue.Empty:
            pass
        if self._mon_stop is not None:
            self.after(150, self._poll_queue)
        else:
            self._polling = False

    def _render_realtime(self, sample: dict, n: int, dt: float):
        self.g_rpm.set(to_float(sample.get("RPM (rpm)")))
        self.g_spd.set(to_float(sample.get("Speed (km/h)")))
        self.g_clt.set(to_float(sample.get("Coolant (C)")))
        self.g_ld.set(to_float(sample.get("Engine load (%)")))
        scaled = dict(self.history)
        if "Speed (km/h)" in self.history:
            scaled["Speed (km/h)"] = collections.deque(
                [v * 30 for v in self.history["Speed (km/h)"]], maxlen=90)
        self.chart_drive.draw(scaled)
        self.chart_fuel.draw(self.history)
        rate = (1.0 / dt) if dt > 0 else 0
        self.dash_status.config(
            text=f"#{n}  ·  {rate:.1f}/s  ·  "
                 f"{sample.get('RPM (rpm)')} rpm")
        for i in self.mon_tree.get_children():
            self.mon_tree.delete(i)
        for k, v in sample.items():
            self.mon_tree.insert("", "end", text=k, values=(v,), tags=("even",))

    def on_monitor_toggle(self):
        if self._mon_stop is not None:  # running -> stop
            self._mon_stop.set()
            self._mon_stop = None
            self.btn_dash.config(text="▶  Start realtime", style="Accent.TButton")
            self.dash_status.config(text="Stopped")
            self.write("Monitor stopped.\n")
            return
        try:
            interval = max(0.3, float(self.interval_var.get()))
        except ValueError:
            messagebox.showerror("Bad interval", "Interval must be a number, e.g. 0.5")
            return
        logfile = self.csv_var.get().strip() or None
        self._mon_stop = threading.Event()
        stop = self._mon_stop
        self._samples = 0
        self._last_t = 0.0
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self.btn_dash.config(text="■  Stop", style="Danger.TButton")
        self.write(f"Realtime started every {interval}s"
                   + (f" -> {logfile}" if logfile else "") + "\n")
        if not self._polling:
            self._polling = True
            self.after(150, self._poll_queue)

        def _loop():
            try:
                self.client.stream_live(interval=interval, count=0,
                                        callback=self._push_sample,
                                        logfile=logfile, stop_event=stop)
            except Exception as e:
                self.write(f"MONITOR FAILED: {e}\n")
            finally:
                self.call_ui(lambda: self.btn_dash.config(
                    text="▶  Start realtime", style="Accent.TButton"))
                self._mon_stop = None
        threading.Thread(target=_loop, daemon=True).start()

    # ================= ABS =================
    def on_abs_read(self):
        def _do():
            try:
                adtcs, ainfo = self.client.read_abs_dtcs()
                self.write(f"\nABS ({ainfo.get('source')}): {ainfo.get('note')}\n")
                if not adtcs:
                    self.write("  No ABS C-codes via generic OBD.\n")
                else:
                    for d in adtcs:
                        self.write(f"  {d.code} — {d.description}\n")
                self._update_abs_tree(adtcs, str(ainfo.get("source")))
                self.call_ui(lambda: self.stack.select(self.tab_abs))
            except Exception as e:
                self.write(f"ABS READ FAILED: {e}\n")
        self.run_bg(_do)

    def on_abs_clear(self):
        if not messagebox.askyesno("Confirm",
                "Clear ABS codes via Mode 04?\nDo this only after noting/fixing the cause.\n"
                "This also clears engine codes and resets I/M readiness."):
            return
        def _do():
            try:
                res = self.client.clear_abs()
                self.write(("ABS clear sent.\n" if res["ok"] else "ABS clear got no response.\n")
                           + res["warning"] + "\n")
                self.on_abs_read()
            except Exception as e:
                self.write(f"ABS CLEAR FAILED: {e}\n")
        self.run_bg(_do)

    def on_abs_probe(self):
        hdr = self.abs_hdr_var.get().strip() or None
        def _do():
            try:
                probe = self.client.probe_abs_module(header=hdr)
                self.write(f"\nABS probe @ {probe['header']}:\n")
                for a in probe["attempts"]:
                    self.write(f"  [{a.get('verdict', 'data' if a['data'] else 'no data')}] "
                               f"{a['cmd']} -> {a['reply']}\n")
                self.write(probe["note"] + "\n")
            except Exception as e:
                self.write(f"ABS PROBE FAILED: {e}\n")
        self.run_bg(_do)

    def on_abs_raw(self):
        cmd = self.abs_cmd_var.get().strip()
        hdr = self.abs_hdr_var.get().strip() or None
        if not cmd:
            messagebox.showerror("Missing command", "Enter a raw command, e.g. 19 02 FF")
            return
        def _do():
            try:
                resp = self.client.query_abs_raw(cmd, tx_header=hdr)
                self.write(f"\nABS raw [{hdr or 'default'}] {cmd} ->\n{resp}\n")
            except Exception as e:
                self.write(f"ABS RAW FAILED: {e}\n")
        self.run_bg(_do)

    def _update_abs_tree(self, adtcs, source: str):
        rows = [(d.code, (d.description,)) for d in adtcs]
        status = f"{len(adtcs)} code(s) · {source}"
        color = RED if adtcs else GREEN
        self.call_ui(lambda: (fill_tree(self.abs_tree, rows),
                               self.abs_status.config(text=status, fg=color)))

    # ================= I/M =================
    def on_im(self):
        def _do():
            try:
                im = self.client.im_readiness()
                self.write("\n" + self.client.format_im(im) + "\n")
                self._update_im_tree(im)
                self.call_ui(lambda: self.stack.select(self.tab_im))
            except Exception as e:
                self.write(f"I/M FAILED: {e}\n")
        self.run_bg(_do)

    def _update_im_tree(self, im: dict):
        rows = []
        for m in im["monitors"]:
            st = "N/A" if not m["available"] else ("Complete" if m["complete"] else "INCOMPLETE")
            rows.append((m["label"], (st,)))
        status = f"I/M: {im['ready_str']}  (ignition: {im.get('ignition_type')})"
        color = GREEN if im["ready"] else AMBER
        self.call_ui(lambda: (fill_tree(self.im_tree, rows),
                               self.im_status.config(text=status, fg=color)))

    # ================= TPMS =================
    def on_tpms_read(self):
        def _do():
            try:
                tdtcs, tinfo = self.client.read_tpms_dtcs()
                self.write(f"\nTPMS ({tinfo.get('source')}): {tinfo.get('note')}\n")
                if not tdtcs:
                    self.write("  No TPMS codes via generic OBD.\n")
                else:
                    for d in tdtcs:
                        self.write(f"  {d.code} — {d.description}\n")
                self._update_tpms_tree(tdtcs, str(tinfo.get("source")))
                self.call_ui(lambda: self.stack.select(self.tab_tpms))
            except Exception as e:
                self.write(f"TPMS READ FAILED: {e}\n")
        self.run_bg(_do)

    def on_tpms_live(self):
        def _do():
            try:
                t = self.client.read_tpms_live()
                if t.get("supported") and t.get("psi"):
                    self.write("\nLive tire pressures (psi):\n")
                    for k, v in t["psi"].items():
                        self.write(f"  {k}: {v}\n")
                    psi = t["psi"]
                    self.call_ui(lambda: [self.tpms_gauges[k].set(str(psi.get(k, "--")))
                                           for k in self.tpms_gauges])
                    self.call_ui(lambda: self.tpms_status.config(
                        text="live pressures shown", fg=GREEN))
                else:
                    self.write(f"\nTPMS live: {t.get('note')}\n")
                    self.call_ui(lambda: self.tpms_status.config(
                        text="live pressures unavailable", fg=AMBER))
                self.call_ui(lambda: self.stack.select(self.tab_tpms))
            except Exception as e:
                self.write(f"TPMS LIVE FAILED: {e}\n")
        self.run_bg(_do)

    def on_tpms_register(self):
        ids = {c: self.tpms_id_vars[c].get() for c in ("FL", "FR", "RL", "RR")}
        if not all(v.strip() for v in ids.values()):
            messagebox.showerror("Missing IDs", "Enter all 4 sensor IDs (7-8 hex digits each).")
            return
        if not messagebox.askyesno("Confirm",
                f"Write these IDs to the TPMS ECU?\nFL={ids['FL']} FR={ids['FR']} "
                f"RL={ids['RL']} RR={ids['RR']}\nIgnition ON, engine OFF."):
            return
        def _do():
            try:
                res = self.client.register_tpms_ids(ids)
                if res["ok"]:
                    self.write("\nTPMS IDs registered:\n")
                    for s in res.get("steps", []):
                        self.write(f"  {s}\n")
                    self.write((res.get("note") or "") + "\n")
                else:
                    self.write(f"\nTPMS REGISTER FAILED: {res['error']}\n")
            except Exception as e:
                self.write(f"TPMS REGISTER FAILED: {e}\n")
        self.run_bg(_do)

    def on_tpms_raw(self):
        cmd = self.tpms_cmd_var.get().strip()
        hdr = self.tpms_hdr_var.get().strip() or None
        if not cmd or cmd == "22":
            messagebox.showerror("Missing PID", "Enter your model's documented PID, e.g. 22 F411")
            return
        def _do():
            try:
                resp = self.client.query_module(cmd, tx_header=hdr)
                self.write(f"\nTPMS raw [{hdr or 'default'}] {cmd} ->\n{resp}\n")
            except Exception as e:
                self.write(f"TPMS RAW FAILED: {e}\n")
        self.run_bg(_do)

    def _update_tpms_tree(self, tdtcs, source: str):
        rows = [(d.code, (d.description,)) for d in tdtcs]
        status = f"{len(tdtcs)} code(s) · {source}"
        color = RED if tdtcs else GREEN
        self.call_ui(lambda: (fill_tree(self.tpms_tree, rows),
                               self.tpms_status.config(text=status, fg=color)))


if __name__ == "__main__":
    App(demo_default="--demo" in sys.argv).mainloop()
