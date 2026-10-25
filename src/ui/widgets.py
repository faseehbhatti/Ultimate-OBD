"""Custom widgets for the OBD reader GUI (cards, nav rail, gauges, charts)."""

from __future__ import annotations

import collections
import tkinter as tk

from .theme import (ACCENT, BORDER, FONT, FAINT, FIELD, MUTED, RED, SURFACE,
                    SURFACE_2, SURFACE_3, TEXT, blend, label)

__all__ = ["Card", "NavItem", "PageStack", "Gauge", "TrendChart", "Toggle",
           "style_tree", "fill_tree"]


class Card(tk.Frame):
    """Flat panel with a 1px border; put children in .body (padded)."""

    def __init__(self, parent, padding: int = 16, bg: str = SURFACE,
                 border: str = BORDER, **kwargs):
        super().__init__(parent, bg=bg, highlightbackground=border,
                         highlightthickness=1, bd=0, takefocus=0, **kwargs)
        self.bg = bg
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


class NavItem(tk.Frame):
    """Sidebar row: accent bar + glyph + label, with hover and active states."""

    def __init__(self, parent, icon: str, title: str, command):
        super().__init__(parent, bg=parent.cget("bg"), cursor="hand2")
        self._active = False
        self._base = parent.cget("bg")
        self.bar = tk.Frame(self, bg=self._base, width=3)
        self.bar.pack(side="left", fill="y")
        self.inner = tk.Frame(self, bg=self._base)
        self.inner.pack(side="left", fill="x", expand=True,
                        padx=(14, 10), pady=9)
        self.icon = tk.Label(self.inner, text=icon, bg=self._base, fg=FAINT,
                             font=(FONT, 11), width=2, anchor="w",
                             bd=0, highlightthickness=0)
        self.icon.pack(side="left")
        self.label = tk.Label(self.inner, text=title, bg=self._base, fg=MUTED,
                              font=(FONT, 9), anchor="w",
                              bd=0, highlightthickness=0)
        self.label.pack(side="left", padx=(2, 0))
        for widget in (self, self.inner, self.icon, self.label):
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", self._hover_on)
            widget.bind("<Leave>", self._hover_off)

    def _paint(self, bg: str) -> None:
        for widget in (self, self.inner, self.icon, self.label):
            widget.configure(bg=bg)

    def _hover_on(self, _event=None) -> None:
        if not self._active:
            self._paint(SURFACE_2)
            self.icon.configure(fg=MUTED)
            self.label.configure(fg=TEXT)

    def _hover_off(self, _event=None) -> None:
        if not self._active:
            self._paint(self._base)
            self.icon.configure(fg=FAINT)
            self.label.configure(fg=MUTED)

    def set_active(self, active: bool) -> None:
        self._active = active
        bg = SURFACE_2 if active else self._base
        self._paint(bg)
        self.bar.configure(bg=ACCENT if active else self._base)
        self.icon.configure(fg=ACCENT if active else FAINT)
        self.label.configure(fg=TEXT if active else MUTED,
                             font=(FONT, 9, "bold" if active else "normal"))


class PageStack(tk.Frame):
    """Stacked full-page frames with a title/subtitle callback (Notebook-like)."""

    def __init__(self, parent, on_select=None):
        super().__init__(parent, bg=parent.cget("bg"))
        self._pages: dict[tk.Widget, tuple[str, str]] = {}
        self._current: tk.Widget | None = None
        self.on_select = on_select
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def add(self, page: tk.Widget, title: str, subtitle: str = "") -> None:
        self._pages[page] = (title, subtitle)
        page.grid(row=0, column=0, sticky="nsew")

    def select(self, page: tk.Widget | None = None):
        if page is None:
            return self._current
        page.tkraise()
        self._current = page
        title, subtitle = self._pages.get(page, ("", ""))
        if self.on_select is not None:
            self.on_select(page, title, subtitle)
        return page


class Gauge(tk.Frame):
    """KPI tile: micro title, large value + unit, thin rounded level bar."""

    def __init__(self, parent, title: str, unit: str, vmin: float, vmax: float,
                 width: int = 200, bar_color: str = "#2e86de"):
        super().__init__(parent, bg=SURFACE, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        self.vmin, self.vmax = vmin, vmax
        self.bar_color = bar_color
        self.unit = unit
        self._width = width
        self._frac = 0.0
        inner = tk.Frame(self, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=14, pady=11)
        label(inner, title.upper(), size=7, weight="bold", fg=MUTED,
              bg=SURFACE).pack(fill="x")
        vrow = tk.Frame(inner, bg=SURFACE)
        vrow.pack(fill="x", pady=(3, 7))
        self.val_lbl = label(vrow, "--", size=20, weight="bold", fg=TEXT,
                             bg=SURFACE, family="Segoe UI Semibold")
        self.val_lbl.pack(side="left")
        self.unit_lbl = label(vrow, unit, size=8, fg=FAINT, bg=SURFACE)
        self.unit_lbl.pack(side="left", padx=(5, 0), pady=(0, 4), anchor="s")
        self.canvas = tk.Canvas(inner, height=6, bg=SURFACE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _e: self._draw())

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or self._width
        y = 3
        c.create_line(3, y, max(4, w - 3), y, fill=SURFACE_3, width=6,
                      capstyle="round")
        if self._frac > 0.005:
            c.create_line(3, y, 3 + (w - 6) * self._frac, y,
                          fill=self.bar_color, width=6, capstyle="round")

    def set(self, value: float | None):
        if value is None:
            self.val_lbl.configure(text="--")
            self._frac = 0.0
            self._draw()
            return
        text = f"{value:,.0f}" if abs(value) >= 20 else f"{value:.1f}"
        self.val_lbl.configure(text=text)
        self._frac = min(1.0, max(0.0, (value - self.vmin) /
                                  (self.vmax - self.vmin)))
        self._draw()


class TrendChart(tk.Frame):
    """Scrolling multi-series chart with a soft area fill on the first series."""

    def __init__(self, parent, title: str, series: list[tuple[str, str]],
                 vmin: float, vmax: float, height: int = 130):
        super().__init__(parent, bg=SURFACE, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        self.vmin, self.vmax = vmin, vmax
        self.series = series  # [(key, color)]
        inner = tk.Frame(self, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=14, pady=(11, 10))
        head = tk.Frame(inner, bg=SURFACE)
        head.pack(fill="x", pady=(0, 6))
        label(head, title.upper(), size=7, weight="bold", fg=MUTED,
              bg=SURFACE).pack(side="left")
        for key, color in reversed(series):
            label(head, f"● {key}", size=8, fg=color, bg=SURFACE).pack(
                side="right", padx=(10, 0))
        self.canvas = tk.Canvas(inner, height=height, bg=SURFACE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._has_data = False
        self.canvas.bind("<Configure>", self._on_resize)

    def _grid(self, width: int, height: int) -> None:
        for i in (0.25, 0.5, 0.75):
            y = 4 + (height - 8) * i
            self.canvas.create_line(0, y, width, y, fill="#18232f")

    def _placeholder(self) -> None:
        if self._has_data:
            return
        c = self.canvas
        c.delete("all")
        width, height = c.winfo_width(), c.winfo_height()
        if width < 40 or height < 30:
            return
        self._grid(width, height)
        c.create_text(width / 2, height / 2,
                      text="Start realtime to plot live values",
                      fill=FAINT, font=(FONT, 8))

    def _on_resize(self, _event=None) -> None:
        self._placeholder()

    def draw(self, history: dict[str, collections.deque]):
        c = self.canvas
        c.delete("all")
        width, height = c.winfo_width(), c.winfo_height()
        if width < 40 or height < 30:
            return
        self._grid(width, height)
        self._has_data = False
        n = 90
        for index, (key, color) in enumerate(self.series):
            points = list(history.get(key, []))[-n:]
            if len(points) < 2:
                continue
            self._has_data = True
            coords = []
            if len(points) < n:
                # Few samples: spread them across the full width so the first
                # seconds of data are readable instead of a dot at the edge.
                spacing = (width - 8) / (len(points) - 1)
                start = 4
            else:
                spacing = (width - 8) / (n - 1)
                start = width - 4 - (n - 1) * spacing
            for i, value in enumerate(points):
                x = start + i * spacing
                frac = (value - self.vmin) / (self.vmax - self.vmin)
                frac = min(1.0, max(0.0, frac))
                y = height - 6 - frac * (height - 12)
                coords += [x, y]
            if index == 0:
                c.create_polygon(*coords, coords[-2], height - 2,
                                 coords[0], height - 2,
                                 fill=blend(SURFACE, color, 0.16), outline="")
            c.create_line(*coords, fill=color, width=2)
            c.create_oval(coords[-2] - 3, coords[-1] - 3,
                          coords[-2] + 3, coords[-1] + 3,
                          fill=color, outline=SURFACE)
        if not self._has_data:
            c.create_text(width / 2, height / 2,
                          text="Start realtime to plot live values",
                          fill=FAINT, font=(FONT, 8))


class Toggle(tk.Frame):
    """Small canvas switch bound to a tk.BooleanVar (replaces ttk's ugly check)."""

    def __init__(self, parent, text: str, variable: tk.BooleanVar,
                 bg: str = SURFACE, command=None):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var = variable
        self.command = command
        self.canvas = tk.Canvas(self, width=36, height=18, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left")
        self.label = tk.Label(self, text=text, bg=bg, fg=MUTED,
                              font=(FONT, 8), bd=0, highlightthickness=0)
        self.label.pack(side="left", padx=(8, 0))
        for widget in (self, self.canvas, self.label):
            widget.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *_args: self._draw())
        self._draw()

    def _toggle(self, _event=None):
        self.var.set(not self.var.get())
        if self.command is not None:
            self.command()

    def _draw(self):
        c = self.canvas
        c.delete("all")
        on = bool(self.var.get())
        track = ACCENT if on else SURFACE_3
        c.create_oval(1, 1, 17, 17, fill=track, outline="")
        c.create_oval(19, 1, 35, 17, fill=track, outline="")
        c.create_rectangle(9, 1, 27, 17, fill=track, outline="")
        knob_x = 27 if on else 9
        c.create_oval(knob_x - 6, 4, knob_x + 6, 16,
                      fill="#04231f" if on else MUTED, outline="")
        self.label.configure(fg=TEXT if on else MUTED)


def style_tree(tree: tk.Widget) -> None:
    """Install the striped/warning tags shared by every table."""
    tree.tag_configure("even", background=SURFACE, foreground=TEXT)
    tree.tag_configure("odd", background="#15202b", foreground=TEXT)
    tree.tag_configure("warn", background="#2a2214", foreground="#fbbf24")
    tree.tag_configure("ok", background="#11241f", foreground="#34d399")


def fill_tree(tree: tk.Widget, rows) -> None:
    """Replace a Treeview's contents. rows = [(text, values-tuple), ...]."""
    for item in tree.get_children():
        tree.delete(item)
    for index, (text, values) in enumerate(rows):
        joined = str(text) + " " + " ".join(str(v) for v in values)
        value_text = " ".join(str(v) for v in values).strip()
        if ("INCOMPLETE" in joined or "pending" in joined.lower()
                or "FAIL" in joined):
            tags = ("warn",)
        elif value_text == "Complete":
            tags = ("ok",)
        else:
            tags = ("odd",) if index % 2 else ("even",)
        tree.insert("", "end", text=text, values=values, tags=tags)
