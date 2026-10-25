"""Visual foundation for the OBD reader GUI: palette, fonts, ttk theming.

Every screen imports these constants so the whole app stays one design system.
Pure stdlib (Tkinter/ttk) — no extra dependency to package into the exe.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
BG = "#0b0f14"          # window background
SIDEBAR = "#0d141c"     # navigation rail
SURFACE = "#121b24"     # cards
SURFACE_2 = "#17222d"   # raised surface / hover
SURFACE_3 = "#1d2a37"   # inputs / secondary buttons
FIELD = "#0e151d"       # text fields, table headings, log body
BORDER = "#223141"
TEXT = "#e6eef7"
MUTED = "#8a9bb0"
FAINT = "#5c6d80"
ACCENT = "#2dd4bf"      # teal: primary action / live state
ACCENT_DIM = "#123733"
BLUE = "#60a5fa"
AMBER = "#fbbf24"
RED = "#f87171"
GREEN = "#34d399"

FONT = "Segoe UI"
MONO = "Consolas"

STATUS_COLORS = {"green": GREEN, "red": RED, "orange": AMBER}


def blend(color_a: str, color_b: str, t: float) -> str:
    """Linear blend of two #rrggbb colors, t=0 -> a, t=1 -> b."""
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t)
                                   for i in range(3))


def label(parent, text: str = "", *, size: int = 9, weight: str = "normal",
          fg: str = TEXT, bg: str = SURFACE, family: str = FONT,
          anchor: str = "w", **kwargs) -> tk.Label:
    """A tk.Label pre-wired to the palette (no theme background surprises)."""
    return tk.Label(parent, text=text, font=(family, size, weight), fg=fg, bg=bg,
                    anchor=anchor, justify="left", bd=0, highlightthickness=0,
                    **kwargs)


def divider(parent, bg: str = BORDER) -> tk.Frame:
    """One-pixel horizontal rule."""
    return tk.Frame(parent, bg=bg, height=1)


def chip(parent, text: str, *, fg: str = MUTED, bg: str = SURFACE_2) -> tk.Label:
    """Small rounded-ish badge used for hints and step markers."""
    return tk.Label(parent, text=text, font=(FONT, 8), fg=fg, bg=bg,
                    padx=9, pady=4, bd=0, highlightthickness=0)


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Install the dark ttk styles used by buttons, inputs and tables."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.option_add("*Font", (FONT, 9))
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT)

    style.configure(".", background=BG, foreground=TEXT, font=(FONT, 9))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)

    # -- buttons -----------------------------------------------------------
    style.configure("Accent.TButton", background=ACCENT, foreground="#05201c",
                    borderwidth=0, focusthickness=0, relief="flat",
                    padding=(16, 9), font=(FONT, 9, "bold"))
    style.map("Accent.TButton",
              background=[("active", "#5eead4"), ("pressed", "#14b8a6"),
                          ("disabled", SURFACE_3)],
              foreground=[("disabled", FAINT)])

    style.configure("Ghost.TButton", background=SURFACE_2, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=SURFACE_2, darkcolor=SURFACE_2,
                    borderwidth=1, focusthickness=0, relief="flat",
                    padding=(13, 7), font=(FONT, 9))
    style.map("Ghost.TButton",
              background=[("active", SURFACE_3), ("pressed", FIELD),
                          ("disabled", SURFACE)],
              foreground=[("disabled", FAINT)])

    style.configure("Danger.TButton", background="#2a1519", foreground=RED,
                    bordercolor="#4a252d", lightcolor="#2a1519", darkcolor="#2a1519",
                    borderwidth=1, focusthickness=0, relief="flat",
                    padding=(13, 7), font=(FONT, 9))
    style.map("Danger.TButton",
              background=[("active", "#3a1d23"), ("pressed", "#4a252d")],
              foreground=[("active", "#fca5a5")])

    style.configure("Small.TButton", background=SURFACE_2, foreground=MUTED,
                    bordercolor=BORDER, lightcolor=SURFACE_2, darkcolor=SURFACE_2,
                    borderwidth=1, focusthickness=0, relief="flat",
                    padding=(9, 4), font=(FONT, 8))
    style.map("Small.TButton",
              background=[("active", SURFACE_3)],
              foreground=[("active", TEXT)])

    # -- inputs ------------------------------------------------------------
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT,
                    insertcolor=ACCENT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(8, 5))
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    style.configure("TCombobox", fieldbackground=FIELD, background=SURFACE_2,
                    foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(8, 5))
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", FIELD)],
              selectforeground=[("readonly", TEXT)],
              bordercolor=[("focus", ACCENT)],
              arrowcolor=[("active", ACCENT)])

    style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT,
                    arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(6, 4))
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])

    style.configure("TCheckbutton", background=SURFACE, foreground=MUTED,
                    focuscolor=SURFACE, indicatorbackground=FIELD,
                    indicatorforeground=ACCENT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER)
    style.map("TCheckbutton",
              background=[("active", SURFACE)],
              foreground=[("active", TEXT)],
              indicatorbackground=[("selected", ACCENT_DIM), ("active", SURFACE_3)],
              indicatorforeground=[("selected", ACCENT)])

    # -- tables ------------------------------------------------------------
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, borderwidth=0, rowheight=26,
                    bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                    font=(FONT, 9))
    style.configure("Treeview.Heading", background=FIELD, foreground=MUTED,
                    borderwidth=0, relief="flat", padding=(9, 6),
                    bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD,
                    font=(FONT, 8, "bold"))
    style.map("Treeview.Heading", background=[("active", FIELD)],
              bordercolor=[("active", FIELD)])
    style.map("Treeview", background=[("selected", ACCENT_DIM)],
              foreground=[("selected", TEXT)],
              bordercolor=[("focus", SURFACE)],
              lightcolor=[("focus", SURFACE)],
              darkcolor=[("focus", SURFACE)])

    # -- scrollbars --------------------------------------------------------
    style.configure("Slim.Vertical.TScrollbar", gripcount=0,
                    background="#2a3a4a", darkcolor=SURFACE, lightcolor=SURFACE,
                    troughcolor=FIELD, bordercolor=FIELD, arrowcolor=MUTED,
                    arrowsize=12, width=10)
    style.map("Slim.Vertical.TScrollbar",
              background=[("active", "#3b4f63")])

    # Completed / warning entities in tables (configured per tree as well).
    style.configure("TPanedwindow", background=BG)

    # Classic scrollbar fallback (e.g. Text widgets created by other code).
    root.option_add("*Scrollbar.background", SURFACE_3)
    root.option_add("*Scrollbar.troughColor", BG)
    root.option_add("*Scrollbar.activeBackground", "#3b4f63")
    root.option_add("*Scrollbar.borderWidth", 0)

    return style
