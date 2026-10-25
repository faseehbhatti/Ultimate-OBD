"""Tkinter GUI for the OBD-II reader.

Visual shell: a dark navigation rail (Connect / Engine / ABS / I/M / TPMS), a
page header with connection state, card-based content, and a resizable Session
Log docked at the bottom. Threading rule: workers never call Tk — they enqueue
callables drained by the UI-thread pump.

Run from the project root:  py src/gui.py  (or  py src/gui.py --demo)
"""

from __future__ import annotations

import collections
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
from ui.theme import (ACCENT, ACCENT_DIM, AMBER, BG, BLUE, BORDER, FAINT,
                      FIELD, FONT, GREEN, MONO, MUTED, RED, SIDEBAR,
                      STATUS_COLORS, SURFACE, SURFACE_2, SURFACE_3, TEXT,
                      apply_theme, chip, divider, label)
from ui.widgets import (Card, Gauge, NavItem, PageStack, Toggle, TrendChart,
                        fill_tree, style_tree)


class App(tk.Tk):
    def __init__(self, demo_default=False):
        super().__init__()
        self.title("OBD Reader — Diagnostics")
        screen_h = self.winfo_screenheight()
        width, height = 1240, min(900, max(720, screen_h - 90))
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(1040, 720)

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
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump_calls)

    # ================= shell =================
    def _build_shell(self):
        """Sidebar + header + page stack + log pane. Pages are added later."""
        self.side = tk.Frame(self, bg=SIDEBAR, width=232)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        self._build_sidebar()

        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=BG, padx=22, pady=14)
        header.pack(fill="x")
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        self.page_title_var = tk.StringVar(value="Connect")
        self.page_sub_var = tk.StringVar(value="")
        label(titles, "", size=17, weight="bold", bg=BG,
              family="Segoe UI Semibold",
              textvariable=self.page_title_var).pack(anchor="w")
        label(titles, "", size=9, fg=MUTED, bg=BG,
              textvariable=self.page_sub_var).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header, bg=BG)
        right.pack(side="right")
        self.demo_badge = tk.Label(right, text="DEMO", font=(FONT, 7, "bold"),
                                   fg=ACCENT, bg=ACCENT_DIM, padx=8, pady=4,
                                   bd=0, highlightthickness=0)
        pill = tk.Frame(right, bg=SURFACE_2, highlightbackground=BORDER,
                        highlightthickness=1, bd=0)
        pill.pack(side="right")
        self.conn_label = tk.Label(pill, text="● Disconnected", font=(FONT, 9, "bold"),
                                   fg=RED, bg=SURFACE_2, padx=12, pady=6,
                                   bd=0, highlightthickness=0)
        self.conn_label.pack()

        divider(main).pack(fill="x", padx=22)

        self.pw = tk.PanedWindow(main, orient="vertical", bg=BG, sashwidth=6,
                                 bd=0, sashrelief="flat")
        self.pw.pack(fill="both", expand=True, padx=16, pady=(10, 14))
        self.stack = PageStack(self.pw, on_select=self._on_page_change)
        self.pw.add(self.stack, minsize=400, stretch="always")
        self._build_log_panel()

    def _build_sidebar(self):
        brand = tk.Frame(self.side, bg=SIDEBAR, padx=20, pady=20)
        brand.pack(fill="x")
        logo = tk.Canvas(brand, width=32, height=32, bg=SIDEBAR,
                         highlightthickness=0, bd=0)
        logo.pack(side="left")
        logo.create_arc(4, 4, 28, 28, start=205, extent=130, style="arc",
                        outline=ACCENT, width=2)
        logo.create_line(16, 16, 23, 10, fill=ACCENT, width=2)
        logo.create_oval(14, 14, 18, 18, fill=ACCENT, outline="")
        names = tk.Frame(brand, bg=SIDEBAR)
        names.pack(side="left", padx=(10, 0))
        label(names, "OBD Reader", size=12, weight="bold", bg=SIDEBAR,
              family="Segoe UI Semibold").pack(anchor="w")
        label(names, "DIAGNOSTICS SUITE", size=6, weight="bold", fg=FAINT,
              bg=SIDEBAR).pack(anchor="w")

        self.nav_area = tk.Frame(self.side, bg=SIDEBAR)
        self.nav_area.pack(fill="x")

        card = Card(self.side, padding=12)
        card.pack(side="bottom", fill="x", padx=14, pady=16)
        label(card.body, "VEHICLE", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x")
        self.side_vehicle_var = tk.StringVar(value="No vehicle detected")
        self.side_vin_var = tk.StringVar(value="VIN —")
        self.side_proto_var = tk.StringVar(value="Protocol —")
        label(card.body, "", size=9, weight="bold", bg=SURFACE,
              textvariable=self.side_vehicle_var, wraplength=176).pack(
                  fill="x", pady=(4, 3))
        label(card.body, "", size=8, fg=MUTED, bg=SURFACE, family="Consolas",
              textvariable=self.side_vin_var, wraplength=176).pack(fill="x")
        label(card.body, "", size=7, fg=FAINT, bg=SURFACE,
              textvariable=self.side_proto_var, wraplength=176).pack(
                  fill="x", pady=(3, 0))
        label(card.body, "Session logs auto-save to logs/", size=7, fg=FAINT,
              bg=SURFACE).pack(fill="x", pady=(8, 0))

    def _build_nav(self):
        label(self.nav_area, "WORKSPACE", size=7, weight="bold", fg=FAINT,
              bg=SIDEBAR).pack(fill="x", padx=20, pady=(16, 6))
        entries = [
            (self.tab_connect, "⌂", "Connect"),
            (self.tab_obd, "◎", "Engine"),
            (self.tab_abs, "◈", "ABS"),
            (self.tab_im, "✓", "I/M Readiness"),
            (self.tab_tpms, "◍", "TPMS"),
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
        head = tk.Frame(card.body, bg=SURFACE, padx=14, pady=8)
        head.pack(fill="x")
        label(head, "SESSION LOG", size=8, weight="bold", fg=MUTED,
              bg=SURFACE).pack(side="left")
        for text, command in (("Open folder", self.on_open_logs),
                              ("Save now", self.on_save_log),
                              ("Clear", self.on_clear_log)):
            ttk.Button(head, text=text, style="Small.TButton",
                       command=command).pack(side="right", padx=(6, 0))
        body = tk.Frame(card.body, bg=FIELD)
        body.pack(fill="both", expand=True)
        self.log = tk.Text(body, bg=FIELD, fg="#c3d1df", insertbackground=ACCENT,
                           selectbackground=ACCENT_DIM, selectforeground=TEXT,
                           relief="flat", bd=0, highlightthickness=0,
                           wrap="word", font=(MONO, 9), padx=14, pady=8,
                           height=6)
        scroll = ttk.Scrollbar(body, orient="vertical",
                               command=self.log.yview,
                               style="Slim.Vertical.TScrollbar")
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.pw.add(wrap, minsize=96, height=140, stretch="never")
        self.log.insert("end", "Diagnostic log — every action reports here.\n"
                               "Drag the sash above this panel to resize it.\n"
                               "This log is saved to logs/ automatically when the app closes.\n\n")

    # ================= navigation / header =================
    def _select_page(self, page: tk.Widget):
        self.stack.select(page)

    def _on_page_change(self, page: tk.Widget, title: str, subtitle: str):
        self.page_title_var.set(title)
        self.page_sub_var.set(subtitle)
        for candidate, item in self.nav_items.items():
            item.set_active(candidate is page)

    def _refresh_demo_badge(self):
        if self.demo_var.get():
            self.demo_badge.pack(side="right", padx=(0, 8))
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
        self.log.insert("end", s)
        self.log.see("end")

    def _set_conn_label(self, text: str, color: str):
        self.call_ui(lambda: self.conn_label.config(
            text=text, fg=STATUS_COLORS.get(color, TEXT)))

    def _show_features(self):
        """Jump to the Engine page after a successful connection."""
        self.call_ui(lambda: self.stack.select(self.tab_obd))

    # ================= Connect page =================
    def _build_connect_tab(self):
        page = tk.Frame(self.stack, bg=BG)
        self.tab_connect = page
        self.stack.add(page, "Connect", "Pair your adapter, then let the app identify the car.")
        page.grid_columnconfigure(0, weight=2, uniform="cols")
        page.grid_columnconfigure(1, weight=3, uniform="cols")
        page.grid_rowconfigure(2, weight=1)

        ready = Card(page, padding=14)
        ready.grid(row=0, column=0, columnspan=2, sticky="ew")
        rrow = tk.Frame(ready.body, bg=SURFACE)
        rrow.pack(fill="x")
        head = tk.Frame(rrow, bg=SURFACE)
        head.pack(side="left")
        label(head, "READY TO SCAN", size=7, weight="bold", fg=ACCENT,
              bg=SURFACE).pack(anchor="w")
        label(head, "Ready when you are.", size=14, weight="bold",
              bg=SURFACE, family="Segoe UI Semibold").pack(anchor="w", pady=(1, 0))
        steps = tk.Frame(rrow, bg=SURFACE)
        steps.pack(side="right")
        for text in ("1  Pair the adapter", "2  Select the port", "3  Connect & detect"):
            chip(steps, text).pack(side="left", padx=(6, 0))

        # -- connection settings ------------------------------------------
        settings = Card(page, padding=16)
        settings.grid(row=1, column=0, sticky="nsew", pady=(12, 0), padx=(0, 6))
        label(settings.body, "CONNECTION", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x")
        label(settings.body, "Adapter link", size=12, weight="bold",
              bg=SURFACE).pack(fill="x", pady=(1, 0))
        label(settings.body, "Serial port the ELM327 exposed after pairing.",
              size=8, fg=MUTED, bg=SURFACE).pack(fill="x", pady=(1, 12))

        form = tk.Frame(settings.body, bg=SURFACE)
        form.pack(fill="x")
        form.grid_columnconfigure(1, weight=1)
        label(form, "COM port", size=8, fg=MUTED, bg=SURFACE).grid(
            row=0, column=0, sticky="w", pady=3)
        self.port_var = tk.StringVar()
        port_row = tk.Frame(form, bg=SURFACE)
        port_row.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=3)
        self.port_box = ttk.Combobox(port_row, textvariable=self.port_var, width=12)
        self.port_box.pack(side="left", fill="x", expand=True)
        ttk.Button(port_row, text="Refresh", style="Small.TButton",
                   command=self.refresh_ports).pack(side="left", padx=(6, 0))

        label(form, "Baud rate", size=8, fg=MUTED, bg=SURFACE).grid(
            row=1, column=0, sticky="w", pady=3)
        self.baud_var = tk.StringVar(value="auto")
        ttk.Combobox(form, textvariable=self.baud_var, width=12,
                     values=["auto", "38400", "9600", "115200", "230400"]).grid(
                         row=1, column=1, sticky="w", padx=(10, 0), pady=3)

        self.demo_var = tk.BooleanVar(value=self.client.demo)
        Toggle(settings.body, "Demo mode — explore without a car",
               self.demo_var, command=self._on_demo_toggle).pack(anchor="w", pady=(12, 0))
        divider(settings.body).pack(fill="x", pady=12)
        ttk.Button(settings.body, text="Connect & detect vehicle",
                   style="Accent.TButton", command=self.on_connect_detect).pack(
                       fill="x")
        label(settings.body, "Ignition ON for codes · engine running for live data.",
              size=8, fg=FAINT, bg=SURFACE).pack(fill="x", pady=(10, 0))

        # -- vehicle identity ---------------------------------------------
        identity = Card(page, padding=16)
        identity.grid(row=1, column=1, sticky="nsew", pady=(12, 0), padx=(6, 0))
        label(identity.body, "VEHICLE IDENTITY", size=7, weight="bold",
              fg=FAINT, bg=SURFACE).pack(fill="x")
        label(identity.body, "Everything the app knows about this car.",
              size=12, weight="bold", bg=SURFACE).pack(fill="x", pady=(1, 0))
        label(identity.body, "Decoded from the VIN; edit below if it can't be read.",
              size=8, fg=MUTED, bg=SURFACE).pack(fill="x", pady=(1, 12))

        self.home_vars = {}
        label(identity.body, "VIN", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x")
        self.home_vars["vin"] = tk.StringVar(value="--")
        label(identity.body, "", size=10, fg=TEXT, bg=SURFACE,
              family="Consolas", textvariable=self.home_vars["vin"],
              wraplength=470).pack(fill="x", pady=(1, 8))

        pairs = tk.Frame(identity.body, bg=SURFACE)
        pairs.pack(fill="x", pady=(0, 8))
        for index, (key, title) in enumerate((("conn", "STATUS"),
                                              ("profile", "PROFILE"))):
            cell = tk.Frame(pairs, bg=SURFACE)
            cell.grid(row=0, column=index, sticky="w",
                      padx=(0, 28 if index == 0 else 0))
            pairs.grid_columnconfigure(index, weight=1, uniform="pair")
            label(cell, title, size=7, weight="bold", fg=FAINT,
                  bg=SURFACE).pack(fill="x")
            var = tk.StringVar(value="--")
            self.home_vars[key] = var
            label(cell, "", size=9, fg=MUTED, bg=SURFACE,
                  textvariable=var).pack(fill="x", pady=(1, 0))

        label(identity.body, "ABS PATH", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x")
        self.home_vars["abs"] = tk.StringVar(value="--")
        label(identity.body, "", size=9, fg=MUTED, bg=SURFACE,
              textvariable=self.home_vars["abs"], wraplength=470).pack(
                  fill="x", pady=(1, 8))

        divider(identity.body).pack(fill="x", pady=(0, 10))
        label(identity.body, "IDENTIFY THE CAR", size=7, weight="bold",
              fg=FAINT, bg=SURFACE).pack(fill="x", pady=(0, 4))
        picker = tk.Frame(identity.body, bg=SURFACE)
        picker.pack(fill="x")
        for col, text in enumerate(("MAKE", "YEAR", "MODEL")):
            label(picker, text, size=7, weight="bold", fg=FAINT,
                  bg=SURFACE).grid(row=0, column=col, sticky="w", padx=(0, 8))
        self.make_var = tk.StringVar(value="")
        self.make_box = ttk.Combobox(picker, textvariable=self.make_var,
                                     width=12, state="readonly",
                                     values=sorted(BRANDS))
        self.make_box.grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.make_box.bind("<<ComboboxSelected>>", lambda _e: self.on_make_pick())
        self.year_var = tk.StringVar(value="")
        ttk.Entry(picker, textvariable=self.year_var, width=7).grid(
            row=1, column=1, sticky="w", padx=(0, 8))
        self.model_var = tk.StringVar(value="")
        self.model_box = ttk.Combobox(picker, textvariable=self.model_var,
                                      width=17, state="readonly")
        self.model_box.grid(row=1, column=2, sticky="w", padx=(0, 8))
        self.model_box.bind("<<ComboboxSelected>>", lambda _e: self.on_model_pick())
        ttk.Button(picker, text="Set", style="Small.TButton",
                   command=self.on_manual_vehicle).grid(row=1, column=3, sticky="w")

        # -- first-run tips ----------------------------------------------
        tips = Card(page, padding=10)
        tips.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        cols = tk.Frame(tips.body, bg=SURFACE)
        cols.pack(fill="both", expand=True)
        for index, (title, body) in enumerate((
                ("Bluetooth first",
                 "Pair in Windows Settings so it exposes a COM port. COM3 may "
                 "refuse — try COM4 or Auto."),
                ("Ignition state",
                 "Key ON, engine OFF for stored codes. Run the engine for live "
                 "data and monitor tests."),
                ("Nothing to lose",
                 "Tick Demo to explore every screen. Real sessions save their "
                 "logs automatically."))):
            col = tk.Frame(cols, bg=SURFACE)
            col.grid(row=0, column=index, sticky="nsew", padx=(0, 24 if index < 2 else 0))
            cols.grid_columnconfigure(index, weight=1, uniform="tips")
            label(col, title, size=9, weight="bold", bg=SURFACE).pack(fill="x")
            label(col, body, size=8, fg=MUTED, bg=SURFACE,
                  wraplength=250).pack(fill="x", pady=(3, 0))

    # ================= Engine page =================
    def _build_obd_tab(self):
        page = tk.Frame(self.stack, bg=BG)
        self.tab_obd = page
        self.stack.add(page, "Engine & live data", "Stored codes, monitor tests, and realtime PIDs.")
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
        self.dtc_status = label(bar, "", size=8, fg=MUTED, bg=SURFACE)
        self.dtc_status.pack(side="right", padx=(12, 4))

        gauges = tk.Frame(page, bg=BG)
        gauges.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tiles = (
            ("Engine RPM", "rpm", 0, 6000, RED, "g_rpm"),
            ("Vehicle speed", "km/h", 0, 200, BLUE, "g_spd"),
            ("Coolant", "°C", 50, 120, AMBER, "g_clt"),
            ("Engine load", "%", 0, 100, GREEN, "g_ld"),
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
            [("RPM (rpm)", RED), ("Speed (km/h)", BLUE)], vmin=0, vmax=6000)
        self.chart_drive.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.chart_fuel = TrendChart(
            charts, "Fuel trims — bank 1",
            [("STFT B1 (%)", "#a78bfa"), ("LTFT B1 (%)", "#22d3ee")],
            vmin=-10, vmax=10, height=110)
        self.chart_fuel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        tables = tk.Frame(page, bg=BG)
        tables.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        tables.grid_rowconfigure(0, weight=1)
        tables.grid_columnconfigure(0, weight=3)
        tables.grid_columnconfigure(1, weight=2)

        codes = Card(tables, padding=12)
        codes.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        label(codes.body, "FAULT CODES", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x", pady=(0, 6))
        self.dtc_tree = self._tree(codes.body, "Code", "Description",
                                   (100, 380), 4)
        self.dtc_tree.pack(fill="both", expand=True)

        live = Card(tables, padding=12)
        live.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        label(live.body, "LIVE PIDS", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x", pady=(0, 6))
        self.mon_tree = self._tree(live.body, "PID", "Value", (180, 100), 4)
        self.mon_tree.pack(fill="both", expand=True)

        controls = Card(page, padding=10)
        controls.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        cbar = tk.Frame(controls.body, bg=SURFACE)
        cbar.pack(fill="x")
        label(cbar, "REALTIME", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(side="left", padx=(2, 10))
        label(cbar, "Interval (s)", size=8, fg=MUTED, bg=SURFACE).pack(side="left")
        self.interval_var = tk.StringVar(value="0.5")
        ttk.Spinbox(cbar, textvariable=self.interval_var, from_=0.3, to=10,
                    increment=0.5, width=5).pack(side="left", padx=(6, 14))
        label(cbar, "CSV log", size=8, fg=MUTED, bg=SURFACE).pack(side="left")
        self.csv_var = tk.StringVar(value="")
        ttk.Entry(cbar, textvariable=self.csv_var, width=18).pack(
            side="left", padx=(6, 6))
        ttk.Button(cbar, text="Browse", style="Small.TButton",
                   command=self.on_browse_csv).pack(side="left")
        self.btn_dash = ttk.Button(cbar, text="▶  Start realtime",
                                   style="Accent.TButton",
                                   command=self.on_monitor_toggle)
        self.btn_dash.pack(side="right")
        self.dash_status = label(cbar, "Stopped", size=8, fg=MUTED, bg=SURFACE)
        self.dash_status.pack(side="right", padx=(0, 12))

    # ================= ABS page =================
    def _build_abs_tab(self):
        page = tk.Frame(self.stack, bg=BG)
        self.tab_abs = page
        self.stack.add(page, "ABS / chassis", "Reads C-codes and probes the skid-control ECU directly.")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        info = Card(page, padding=16)
        info.grid(row=0, column=0, sticky="ew")
        label(info.body, "SKID CONTROL ECU", size=7, weight="bold", fg=ACCENT,
              bg=SURFACE).pack(fill="x")
        label(info.body, "ABS and chassis faults", size=15, weight="bold",
              bg=SURFACE, family="Segoe UI Semibold").pack(fill="x", pady=(1, 3))
        label(info.body, "Reads C-codes through generic OBD (Modes 03 / 07 / 0A) and "
                         "can address the ABS module directly. Every probe reports "
                         "exactly what the ECU said — data, a rejection, or silence.",
              size=9, fg=MUTED, bg=SURFACE, wraplength=1000).pack(fill="x")
        chips = tk.Frame(info.body, bg=SURFACE)
        chips.pack(fill="x", pady=(12, 0))
        for text in ("READ-ONLY READS", "MODES 03 / 07 / 0A", "DIRECT PROBE"):
            chip(chips, text).pack(side="left", padx=(0, 8))

        actions = Card(page, padding=8)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        abar = tk.Frame(actions.body, bg=SURFACE)
        abar.pack(fill="x")
        ttk.Button(abar, text="Read ABS codes", style="Accent.TButton",
                   command=self.on_abs_read).pack(side="left", padx=(0, 6))
        ttk.Button(abar, text="Probe module", style="Ghost.TButton",
                   command=self.on_abs_probe).pack(side="left", padx=(0, 6))
        ttk.Button(abar, text="Clear ABS codes", style="Danger.TButton",
                   command=self.on_abs_clear).pack(side="left")
        self.abs_status = label(abar, "", size=8, fg=MUTED, bg=SURFACE)
        self.abs_status.pack(side="right", padx=(12, 4))

        split = tk.Frame(page, bg=BG)
        split.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        split.grid_rowconfigure(0, weight=1)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)

        codes = Card(split, padding=12)
        codes.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        label(codes.body, "ABS CODES", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x", pady=(0, 6))
        self.abs_tree = self._tree(codes.body, "Code", "Description",
                                   (100, 380), 8)
        self.abs_tree.pack(fill="both", expand=True)

        right = tk.Frame(split, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        guide = Card(right, padding=14)
        guide.grid(row=0, column=0, sticky="ew")
        label(guide.body, "HOW TO READ A PROBE", size=7, weight="bold",
              fg=FAINT, bg=SURFACE).pack(fill="x", pady=(0, 8))
        for tag, color, text in (
                ("DATA", GREEN, "The module answered the service you asked for."),
                ("REJECTION", AMBER, "It replied with an NRC — alive, but refusing "
                                     "that service. Try another session/header."),
                ("SILENCE", RED, "No reply: wrong header, wrong protocol, or the "
                                 "module is off the bus.")):
            row = tk.Frame(guide.body, bg=SURFACE)
            row.pack(fill="x", pady=2)
            label(row, tag, size=7, weight="bold", fg=color, bg=SURFACE,
                  width=10).pack(side="left", anchor="n")
            label(row, text, size=8, fg=MUTED, bg=SURFACE, wraplength=290).pack(
                side="left", fill="x", expand=True)
        label(guide.body, "Pre-2010 Toyotas: if everything is refused, use the "
                          "DLC3 blink procedure (README).",
              size=8, fg=FAINT, bg=SURFACE, wraplength=320).pack(
                  fill="x", pady=(6, 0))

        advanced = Card(right, padding=8)
        advanced.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        label(advanced.body, "RAW QUERY · 7B0 / 19 02 FF", size=7, weight="bold",
              fg=FAINT, bg=SURFACE).pack(fill="x", pady=(0, 6))
        fields = tk.Frame(advanced.body, bg=SURFACE)
        fields.pack(fill="x")
        label(fields, "Header", size=8, fg=MUTED, bg=SURFACE).grid(
            row=0, column=0, sticky="w")
        self.abs_hdr_var = tk.StringVar(value="")
        ttk.Entry(fields, textvariable=self.abs_hdr_var, width=7).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
        label(fields, "Command", size=8, fg=MUTED, bg=SURFACE).grid(
            row=0, column=1, sticky="w")
        self.abs_cmd_var = tk.StringVar(value="19 02 FF")
        ttk.Entry(fields, textvariable=self.abs_cmd_var, width=14).grid(
            row=1, column=1, sticky="w", padx=(0, 8), pady=(2, 0))
        ttk.Button(fields, text="Send", style="Ghost.TButton",
                   command=self.on_abs_raw).grid(row=1, column=2, sticky="w",
                                                 pady=(2, 0))

    # ================= I/M page =================
    def _build_im_tab(self):
        page = tk.Frame(self.stack, bg=BG)
        self.tab_im = page
        self.stack.add(page, "I/M readiness", "Monitor completion status before an emissions test.")
        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=2)
        page.grid_rowconfigure(1, weight=1)

        banner = Card(page, padding=16)
        banner.grid(row=0, column=0, columnspan=2, sticky="ew")
        label(banner.body, "EMISSIONS READINESS", size=7, weight="bold",
              fg=ACCENT, bg=SURFACE).pack(fill="x")
        brow = tk.Frame(banner.body, bg=SURFACE)
        brow.pack(fill="x", pady=(4, 0))
        self.im_status = label(brow, "Not checked yet", size=16, weight="bold",
                               bg=SURFACE, family="Segoe UI Semibold")
        self.im_status.pack(side="left")
        ttk.Button(brow, text="Refresh readiness", style="Accent.TButton",
                   command=self.on_im).pack(side="right")
        label(banner.body, "Mode 01 PID 01 — monitor completion since the last "
                           "code clear. A recent clear resets every monitor.",
              size=8, fg=MUTED, bg=SURFACE).pack(fill="x", pady=(4, 0))

        monitors = Card(page, padding=12)
        monitors.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 5))
        label(monitors.body, "MONITORS", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x", pady=(0, 6))
        self.im_tree = self._tree(monitors.body, "Monitor", "Status",
                                  (280, 200), 10)
        self.im_tree.pack(fill="both", expand=True)

        meaning = Card(page, padding=16)
        meaning.grid(row=1, column=1, sticky="nsew", pady=(10, 0), padx=(5, 0))
        label(meaning.body, "WHAT THIS MEANS", size=7, weight="bold",
              fg=FAINT, bg=SURFACE).pack(fill="x", pady=(0, 10))
        for color, title, text in (
                (GREEN, "Complete", "The monitor ran its test since the last clear."),
                (AMBER, "Incomplete", "Not enough drive time for this monitor — "
                                      "no fault implied, just unfinished."),
                (FAINT, "N/A", "Not fitted to this vehicle.")):
            label(meaning.body, title, size=10, weight="bold", fg=color,
                  bg=SURFACE).pack(fill="x")
            label(meaning.body, text, size=8, fg=MUTED, bg=SURFACE,
                  wraplength=300).pack(fill="x", pady=(0, 10))
        divider(meaning.body).pack(fill="x", pady=(2, 10))
        label(meaning.body, "For a test, readiness must be Complete — or the car "
                            "may be exempt depending on your region's rules.",
              size=8, fg=FAINT, bg=SURFACE, wraplength=300).pack(fill="x")

    # ================= TPMS page =================
    def _build_tpms_tab(self):
        page = tk.Frame(self.stack, bg=BG)
        self.tab_tpms = page
        self.stack.add(page, "TPMS", "Sensor faults, per-corner pressures, and ID writes.")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)

        info = Card(page, padding=12)
        info.grid(row=0, column=0, sticky="ew")
        irow = tk.Frame(info.body, bg=SURFACE)
        irow.pack(fill="x")
        label(irow, "TIRE PRESSURE MONITORING", size=7, weight="bold",
              fg=ACCENT, bg=SURFACE).pack(side="left")
        chips = tk.Frame(irow, bg=SURFACE)
        chips.pack(side="right")
        for text in ("FAULT CODES", "LIVE PRESSURES", "ID WRITES"):
            chip(chips, text).pack(side="left", padx=(6, 0))
        label(info.body, "Fault codes read through OBD on many cars. Per-corner "
                         "pressures need your model's documented PID; target "
                         "pressures are on the door jamb.",
              size=8, fg=MUTED, bg=SURFACE, wraplength=920).pack(
                  fill="x", pady=(4, 0))

        actions = Card(page, padding=8)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        abar = tk.Frame(actions.body, bg=SURFACE)
        abar.pack(fill="x")
        ttk.Button(abar, text="Read TPMS codes", style="Accent.TButton",
                   command=self.on_tpms_read).pack(side="left", padx=(0, 6))
        ttk.Button(abar, text="Live pressures", style="Ghost.TButton",
                   command=self.on_tpms_live).pack(side="left")
        self.tpms_status = label(abar, "", size=8, fg=MUTED, bg=SURFACE)
        self.tpms_status.pack(side="right", padx=(12, 4))

        tiles = tk.Frame(page, bg=BG)
        tiles.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.tpms_gauges = {}
        corners = (("FL (psi)", "FRONT LEFT"), ("FR (psi)", "FRONT RIGHT"),
                   ("RL (psi)", "REAR LEFT"), ("RR (psi)", "REAR RIGHT"))
        for col, (key, title) in enumerate(corners):
            tiles.grid_columnconfigure(col, weight=1, uniform="tires")
            tile = Card(tiles, padding=10)
            tile.grid(row=0, column=col, sticky="nsew",
                      padx=(0 if col == 0 else 4, 0 if col == 3 else 4))
            label(tile.body, title, size=7, weight="bold", fg=FAINT,
                  bg=SURFACE).pack(fill="x")
            row = tk.Frame(tile.body, bg=SURFACE)
            row.pack(fill="x", pady=(2, 0))
            var = tk.StringVar(value="--")
            self.tpms_gauges[key] = var
            label(row, "", size=22, weight="bold", bg=SURFACE,
                  family="Segoe UI Semibold", textvariable=var).pack(side="left")
            label(row, "psi", size=8, fg=FAINT, bg=SURFACE).pack(
                side="left", padx=(5, 0), pady=(0, 5), anchor="s")

        split = tk.Frame(page, bg=BG)
        split.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        split.grid_rowconfigure(0, weight=1)
        for col, weight in ((0, 3), (1, 2), (2, 2)):
            split.grid_columnconfigure(col, weight=weight)

        codes = Card(split, padding=12)
        codes.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        label(codes.body, "TPMS CODES", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x", pady=(0, 6))
        self.tpms_tree = self._tree(codes.body, "Code", "Description",
                                    (100, 260), 6)
        self.tpms_tree.pack(fill="both", expand=True)

        register = Card(split, padding=12)
        register.grid(row=0, column=1, sticky="nsew", padx=5)
        label(register.body, "SENSOR IDS", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x")
        label(register.body, "Write sensor IDs", size=11, weight="bold",
              bg=SURFACE).pack(fill="x", pady=(1, 2))
        label(register.body, "7–8 hex digits each. Needs a verified preset for "
                             "your model — otherwise it refuses.",
              size=8, fg=MUTED, bg=SURFACE, wraplength=230).pack(
                  fill="x", pady=(0, 8))
        self.tpms_id_vars = {}
        id_grid = tk.Frame(register.body, bg=SURFACE)
        id_grid.pack(fill="x")
        for index, corner in enumerate(("FL", "FR", "RL", "RR")):
            row, col = divmod(index, 2)
            cell = tk.Frame(id_grid, bg=SURFACE)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=3)
            label(cell, corner, size=8, fg=MUTED, bg=SURFACE,
                  width=3).pack(side="left")
            var = tk.StringVar(value="")
            self.tpms_id_vars[corner] = var
            ttk.Entry(cell, textvariable=var, width=9).pack(side="left")
        ttk.Button(register.body, text="Register IDs", style="Ghost.TButton",
                   command=self.on_tpms_register).pack(fill="x", pady=(10, 0))

        raw = Card(split, padding=12)
        raw.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        label(raw.body, "RAW MODULE QUERY", size=7, weight="bold", fg=FAINT,
              bg=SURFACE).pack(fill="x")
        label(raw.body, "Needs your model's PID, e.g. 22 F411.",
              size=8, fg=MUTED, bg=SURFACE, wraplength=240).pack(
                  fill="x", pady=(3, 0))
        label(raw.body, "Header", size=8, fg=MUTED, bg=SURFACE).pack(
            fill="x", pady=(8, 2))
        self.tpms_hdr_var = tk.StringVar(value="")
        ttk.Entry(raw.body, textvariable=self.tpms_hdr_var,
                  width=8).pack(fill="x")
        label(raw.body, "Command", size=8, fg=MUTED, bg=SURFACE).pack(
            fill="x", pady=(8, 2))
        self.tpms_cmd_var = tk.StringVar(value="22 ")
        ttk.Entry(raw.body, textvariable=self.tpms_cmd_var,
                  width=12).pack(fill="x")
        ttk.Button(raw.body, text="Send", style="Ghost.TButton",
                   command=self.on_tpms_raw).pack(fill="x", pady=(10, 0))

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
        import sys
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).resolve().parent
        else:
            here = Path(__file__).resolve().parent
            root = here.parent if here.name == "src" else Path.cwd()
        d = root / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log_filename(self, when: datetime | None = None) -> str:
        """E.g. Toyota_Camry_2007_20261001_143022.log (Unknown_* when unset)."""
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
            self._set_conn_label("● Connected", "green")
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
            text=f"Sample #{n}  ·  {rate:.1f}/s  ·  "
                 f"{sample.get('RPM (rpm)')} rpm  ·  "
                 f"{sample.get('Speed (km/h)')} km/h")
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
