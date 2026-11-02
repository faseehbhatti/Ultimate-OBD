"""Custom widgets: cards, nav rail, gauges, charts, tables."""

from __future__ import annotations

import collections
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .theme import (ACCENT, ACCENT_HAIRLINE, BG, BORDER, BORDER_SOFT, DANGER_TEXT,
                    DANGER_WASH, DISPLAY_FONT, FAINT, FONT, INK, LIVE, LIVE_DEEP,
                    LIVE_TEXT, LIVE_WASH, MUTED, MUTE_DEEP, SURFACE, SURFACE_2,
                    SURFACE_3, TEXT, TYPE, blend, label, mono_font)

__all__ = ["Card", "NavItem", "PageStack", "ScrollArea", "Gauge", "TrendChart",
           "Toggle", "Tracked", "Mark", "StatusDot", "style_tree", "fill_tree"]


class Tracked(tk.Canvas):
    """Canvas text with letter-spacing (Tk fonts cannot track natively).

    Used for the wordmark and every mono micro label, so the tracked-caps
    signature of the design system survives in a desktop toolkit.
    """

    def __init__(self, parent, text: str = "", *, size: int = TYPE["micro"],
                 weight: str = "normal", family: str = "JetBrains Mono",
                 fg: str = MUTED, bg: str = SURFACE, tracking: float = 2.0,
                 **kwargs):
        self._face = tkfont.Font(family=family, size=-size, weight=weight)
        self._fg = fg
        self._tracking = tracking
        height = self._face.metrics("linespace") + 2
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0,
                         height=height, **kwargs)
        self._h = height
        self._text = ""
        self.set(text)

    def set(self, text: str) -> None:
        self._text = text or ""
        self.delete("all")
        widths = [self._face.measure(ch) for ch in self._text]
        total = sum(widths) + self._tracking * max(0, len(self._text) - 1)
        self.configure(width=max(1, int(total) + 2))
        x = 0.0
        y = self._h / 2
        for ch, width in zip(self._text, widths):
            self.create_text(x, y, text=ch, anchor="w", font=self._face,
                             fill=self._fg)
            x += width + self._tracking

    def get(self) -> str:
        return self._text


class Mark(tk.Canvas):
    """The brand tile: a solid accent square split by a diagonal slash."""

    def __init__(self, parent, size: int = 30, bg: str = "#ffffff"):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self.create_rectangle(0, 0, size, size, fill=ACCENT, outline="")
        # The carved slash: a paper gap running corner to corner.
        self.create_line(-1, size + 1, size + 1, -1, fill=bg, width=5)


class Card(tk.Frame):
    """Flat panel with a 1px hairline; put children in .body (padded).

    Set seam=True for brand-bearing panels: a 1px accent seam across the top.
    """

    def __init__(self, parent, padding: int = 16, bg: str = SURFACE,
                 border: str = BORDER, seam: bool = False, **kwargs):
        super().__init__(parent, bg=bg, highlightbackground=border,
                         highlightthickness=1, bd=0, takefocus=0, **kwargs)
        self.bg = bg
        if seam:
            tk.Frame(self, bg=ACCENT, height=1).pack(fill="x")
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


_ICON_DRAWERS = {
    "connect": lambda c, col: (
        c.create_line(3, 6, 3, 3, 6, 3, fill=col, width=1),
        c.create_line(11, 3, 14, 3, 14, 6, fill=col, width=1),
        c.create_line(14, 11, 14, 14, 11, 14, fill=col, width=1),
        c.create_line(6, 14, 3, 14, 3, 11, fill=col, width=1),
        c.create_oval(6, 6, 11, 11, outline=col, width=1)),
    "engine": lambda c, col: (
        c.create_oval(2, 2, 15, 15, outline=col, width=1),
        c.create_oval(6, 6, 11, 11, fill=col, outline="")),
    "abs": lambda c, col: (
        c.create_polygon(8.5, 2, 15, 8.5, 8.5, 15, 2, 8.5, fill="",
                         outline=col, width=1)),
    "readiness": lambda c, col: c.create_line(
        3, 9, 7, 13, 14, 4, fill=col, width=1),
    "tpms": lambda c, col: (
        c.create_rectangle(3, 3, 7, 7, outline=col, width=1),
        c.create_rectangle(11, 3, 15, 7, outline=col, width=1),
        c.create_rectangle(3, 11, 7, 15, outline=col, width=1),
        c.create_rectangle(11, 11, 15, 15, outline=col, width=1)),
}


class NavItem(tk.Frame):
    """Sidebar row: accent seam + geometric icon + label, hover/active states."""

    def __init__(self, parent, icon: str, title: str, command):
        super().__init__(parent, bg=parent.cget("bg"), cursor="hand2")
        self._active = False
        self._base = parent.cget("bg")
        self._kind = icon
        self.bar = tk.Frame(self, bg=self._base, width=2)
        self.bar.pack(side="left", fill="y")
        self.inner = tk.Frame(self, bg=self._base)
        self.inner.pack(side="left", fill="x", expand=True,
                        padx=(16, 12), pady=10)
        self.icon = tk.Canvas(self.inner, width=17, height=17, bg=self._base,
                              highlightthickness=0, bd=0)
        self.icon.pack(side="left")
        self.label = tk.Label(self.inner, text=title, bg=self._base, fg=MUTED,
                              font=(FONT, -TYPE["small"], "normal"), anchor="w",
                              bd=0, highlightthickness=0)
        self.label.pack(side="left", padx=(11, 0))
        self._paint_icon(FAINT)
        for widget in (self, self.inner, self.icon, self.label):
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", self._hover_on)
            widget.bind("<Leave>", self._hover_off)

    def _paint_icon(self, color: str) -> None:
        self.icon.delete("all")
        drawer = _ICON_DRAWERS.get(self._kind)
        if drawer is not None:
            drawer(self.icon, color)

    def _paint(self, bg: str) -> None:
        for widget in (self, self.inner, self.icon, self.label):
            widget.configure(bg=bg)

    def _hover_on(self, _event=None) -> None:
        if self._active:
            return
        self._paint(SURFACE_2)
        self.bar.configure(bg=ACCENT_HAIRLINE)
        self._paint_icon(ACCENT)
        self.label.configure(fg=INK)

    def _hover_off(self, _event=None) -> None:
        if self._active:
            return
        self._paint(self._base)
        self.bar.configure(bg=self._base)
        self._paint_icon(FAINT)
        self.label.configure(fg=MUTED)

    def set_active(self, active: bool) -> None:
        self._active = active
        bg = SURFACE_2 if active else self._base
        self._paint(bg)
        self.bar.configure(bg=ACCENT if active else self._base)
        self._paint_icon(ACCENT if active else FAINT)
        self.label.configure(fg=INK if active else MUTED,
                             font=(FONT, -TYPE["small"],
                                   "bold" if active else "normal"))


class ScrollArea(tk.Frame):
    """Vertical scroll host for a page.

    The inner body is kept at least as tall as the viewport, so grid weights
    keep expanding the page when there is room, and only overflow content
    scrolls. The scrollbar hides itself when the page fits.
    """

    def __init__(self, parent, bg: str = BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                                yscrollincrement=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview,
                                 style="Slim.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self._shown = False
        self.body.bind("<Configure>", lambda _e: self._resize())
        self.canvas.bind("<Configure>", lambda _e: self._resize())

    @property
    def scrollable(self) -> bool:
        return self.body.winfo_reqheight() > self.canvas.winfo_height() + 1

    def _on_scroll(self, first: str, last: str) -> None:
        self.vsb.set(first, last)

    def _resize(self) -> None:
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        need = self.body.winfo_reqheight()
        self.canvas.itemconfigure(self._win, width=width,
                                  height=max(need, height))
        self.canvas.configure(scrollregion=(0, 0, width, max(need, height)))
        show = need > height
        if show != self._shown:
            self._shown = show
            if show:
                self.vsb.pack(side="right", fill="y", before=self.canvas)
            else:
                self.vsb.pack_forget()
                self.canvas.yview_moveto(0)


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
    """KPI tile: tracked mono title, display value + unit, thin level bar."""

    def __init__(self, parent, title: str, unit: str, vmin: float, vmax: float,
                 width: int = 200, bar_color: str = ACCENT):
        super().__init__(parent, bg=SURFACE, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        self.vmin, self.vmax = vmin, vmax
        self.bar_color = bar_color
        self.unit = unit
        self._width = width
        self._frac = 0.0
        inner = tk.Frame(self, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        Tracked(inner, title.upper(), size=TYPE["micro"], weight="bold",
                fg=FAINT, bg=SURFACE, tracking=2.2).pack(fill="x")
        vrow = tk.Frame(inner, bg=SURFACE)
        vrow.pack(fill="x", pady=(4, 10))
        self.val_lbl = tk.Label(vrow, text="--", font=(DISPLAY_FONT,
                                                       -TYPE["display"], "normal"),
                                fg=INK, bg=SURFACE, bd=0,
                                highlightthickness=0, anchor="w")
        self.val_lbl.pack(side="left")
        self.unit_lbl = label(vrow, unit, size=TYPE["micro"], fg=FAINT,
                              bg=SURFACE, family="JetBrains Mono")
        self.unit_lbl.pack(side="left", padx=(6, 0), pady=(0, 7), anchor="s")
        self.canvas = tk.Canvas(inner, height=4, width=1, bg=SURFACE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda _e: self._draw())

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or self._width
        y = 2
        c.create_line(0, y, max(1, w), y, fill=SURFACE_3, width=4)
        if self._frac > 0.005:
            c.create_line(0, y, max(2, w * self._frac), y,
                          fill=self.bar_color, width=4)
            # A single accent calibration tick at the head of the level.
            c.create_line(max(2, w * self._frac), y - 3,
                          max(2, w * self._frac), y + 3,
                          fill=ACCENT, width=1)

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

    def __init__(self, parent, title: str, series: list[tuple[str, str, str]],
                 vmin: float, vmax: float, height: int = 130):
        super().__init__(parent, bg=SURFACE, highlightbackground=BORDER,
                         highlightthickness=1, bd=0)
        self.vmin, self.vmax = vmin, vmax
        self.series = series  # [(history key, legend label, color)]
        inner = tk.Frame(self, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=16, pady=(14, 12))
        head = tk.Frame(inner, bg=SURFACE)
        head.pack(fill="x", pady=(0, 8))
        Tracked(head, title.upper(), size=TYPE["micro"], weight="bold",
                fg=FAINT, bg=SURFACE, tracking=2.2).pack(side="left")
        for _key, name, color in reversed(series):
            entry = tk.Frame(head, bg=SURFACE)
            entry.pack(side="right", padx=(12, 0))
            dot = tk.Canvas(entry, width=7, height=7, bg=SURFACE,
                            highlightthickness=0, bd=0)
            dot.create_oval(0, 0, 6, 6, fill=color, outline="")
            dot.pack(side="left", pady=(1, 0))
            label(entry, name, size=TYPE["micro"], fg=MUTED, bg=SURFACE,
                  family="JetBrains Mono").pack(side="left", padx=(5, 0))
        self.canvas = tk.Canvas(inner, height=height, width=1, bg=SURFACE,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._has_data = False
        self.canvas.bind("<Configure>", self._on_resize)

    def _grid(self, width: int, height: int) -> None:
        for i in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = 4 + (height - 8) * i
            self.canvas.create_line(0, y, width, y, fill=BORDER_SOFT)
        for i in (1, 2, 3):
            x = width * i / 4
            self.canvas.create_line(x, 4, x, height - 4, fill=BORDER_SOFT)
        self.canvas.create_text(width - 7, 8, text=f"{self.vmax:g}", anchor="ne",
                                fill=FAINT, font=mono_font(9))
        self.canvas.create_text(width - 7, height - 8, text=f"{self.vmin:g}",
                                anchor="se", fill=FAINT,
                                font=mono_font(9))

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
                      fill=FAINT, font=mono_font(TYPE["micro"]))

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
        for index, (key, _name, color) in enumerate(self.series):
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
                                 fill=blend(SURFACE, color, 0.12), outline="")
            c.create_line(*coords, fill=color, width=2)
            c.create_oval(coords[-2] - 3, coords[-1] - 3,
                          coords[-2] + 3, coords[-1] + 3,
                          fill=color, outline=SURFACE)
        if not self._has_data:
            c.create_text(width / 2, height / 2,
                          text="Start realtime to plot live values",
                          fill=FAINT, font=mono_font(TYPE["micro"]))


class Toggle(tk.Frame):
    """Physical slide switch bound to a tk.BooleanVar (teal when on)."""

    def __init__(self, parent, text: str, variable: tk.BooleanVar,
                 bg: str = SURFACE, command=None):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var = variable
        self.command = command
        self._bg = bg
        self.canvas = tk.Canvas(self, width=42, height=22, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left")
        self.label = tk.Label(self, text=text, bg=bg, fg=MUTED,
                              font=(FONT, -TYPE["small"], "normal"), bd=0,
                              highlightthickness=0)
        self.label.pack(side="left", padx=(11, 0))
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
        track = LIVE_WASH if on else SURFACE_3
        border = LIVE if on else BORDER
        c.create_oval(1, 1, 21, 21, fill=track, outline="")
        c.create_oval(20, 1, 40, 21, fill=track, outline="")
        c.create_rectangle(11, 1, 30, 21, fill=track, outline="")
        # Hairline edge, then the knob: muted when off, lit teal when on.
        c.create_arc(1, 1, 21, 21, start=90, extent=180, style="arc",
                     outline=border)
        c.create_arc(20, 1, 40, 21, start=270, extent=180, style="arc",
                     outline=border)
        c.create_line(11, 1, 30, 1, fill=border)
        c.create_line(11, 21, 30, 21, fill=border)
        knob_x = 31 if on else 11
        if on:
            c.create_oval(knob_x - 10, 1, knob_x + 10, 21, outline=LIVE_DEEP)
        c.create_oval(knob_x - 8, 3, knob_x + 8, 19,
                      fill=LIVE if on else MUTED, outline="")
        self.label.configure(fg=INK if on else MUTED)


class StatusDot(tk.Canvas):
    """Small live indicator with the teal glow vocabulary."""

    def __init__(self, parent, bg: str = SURFACE_2, size: int = 10):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self._size = size
        self._bg = bg
        self.set(MUTE_DEEP)

    def set(self, color: str, glow: bool = False) -> None:
        c = self
        s = self._size
        c.delete("all")
        if glow:
            c.create_oval(0, 0, s, s, fill="", outline=LIVE_DEEP)
        pad = 2 if glow else 1
        c.create_oval(pad, pad, s - pad, s - pad, fill=color, outline="")


def style_tree(tree: tk.Widget) -> None:
    """Install the striped/warning tags shared by every table."""
    tree.tag_configure("even", background=SURFACE, foreground=TEXT)
    tree.tag_configure("odd", background="#f7fafd", foreground=TEXT)
    tree.tag_configure("warn", background=DANGER_WASH,
                       foreground=DANGER_TEXT)
    tree.tag_configure("ok", background=LIVE_WASH, foreground=LIVE_TEXT)


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
