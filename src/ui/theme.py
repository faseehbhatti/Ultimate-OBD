"""Palette, fonts and ttk styles for the GUI.

Pure stdlib Tkinter/ttk plus the bundled OFL fonts in ui/fonts.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# --------------------------------------------------------------------------
# Palette — white paper, black ink, light-blue outlines, one blue signal.
# --------------------------------------------------------------------------

# Ground and surface
BG = "#ffffff"           # page ground — white paper
SIDEBAR = "#f8fbfe"      # navigation rail — a whisper of blue so it separates
SURFACE = "#ffffff"      # raised paper — cards and panels
SURFACE_2 = "#eef5fc"    # inactive chrome, hover
SURFACE_3 = "#dfeaf6"    # one step up: chips, meter tracks
FIELD = "#f8fbfe"        # inset fields and log body

# Hairlines — the light-blue outline that boxes every panel
BORDER = "#bcd8ef"                    # neutral box outline
BORDER_SOFT = "#dcebf9"               # chart grid, quiet separators
ACCENT_HAIRLINE = "#8fbde4"           # outline on interactive chrome

# Text — black at every tier, greying only as it recedes
INK = "#000000"          # headlines, display
TEXT = "#111111"         # body
MUTED = "#4b5563"        # captions, meta
FAINT = "#6b7280"        # subdued labels
MUTE_DEEP = "#9aa3ae"    # disabled

# Blueprint blue — the primary signal
ACCENT = "#2f6fb0"        # links, eyebrows, active nav, chart series
ACCENT_PALE = "#5d97d0"   # hover lift
ACCENT_RICH = "#245c96"   # emphasis, active CTA
ACCENT_DEEP = "#1d4a7a"   # borders against the signal
ACCENT_GLINT = "#e8f2fb"  # highlight wash
ACCENT_FILL = "#bcdcf7"   # solid fill behind the primary button

# Teal — live state, success
LIVE = "#0f8a80"
LIVE_PALE = "#4fb3a9"
LIVE_DEEP = "#0b6a62"
LIVE_TEXT = "#0b6f68"

# Amber — warnings, incomplete monitors
WARN = "#a86a00"
WARN_TEXT = "#8a5a00"
WARN_WASH = "#fdf4e3"

# Red — faults only, used sparingly
DANGER = "#c04a2f"
DANGER_TEXT = "#a83a24"
DANGER_WASH = "#fdece8"

# Ink that sits on an accent fill
ON_ACCENT = "#000000"

# Washes, pre-composited over white paper
ACCENT_WASH = "#eaf3fc"      # accent at 14% over white
ACCENT_WASH_SOFT = "#f4f9fe"  # accent at 7% over white
LIVE_WASH = "#e7f7f5"        # teal at 16% over white

# Legacy semantic aliases (kept so call sites read the same)
ACCENT_DIM = ACCENT_WASH
AMBER = WARN
RED = DANGER_TEXT
GREEN = LIVE
STATUS_COLORS = {"green": LIVE, "red": DANGER_TEXT, "orange": WARN}

# --------------------------------------------------------------------------
# Typography
# --------------------------------------------------------------------------
# Inter carries all proportional text (display, headlines, UI); JetBrains Mono
# handles technical chrome. Windows exposes each variable-font instance as its
# own family, so the light and regular cuts are available by name.

_FONT_DIR = Path(__file__).resolve().parent / "fonts"
if getattr(sys, "frozen", False):
    # PyInstaller one-file: datas land under the extraction root (_MEIPASS),
    # which is what OBDReader.spec targets with its ui/fonts entry.
    _FONT_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "ui" / "fonts"
_FONT_FILES = (
    ("inter.ttf", "Inter"),
    ("jetbrainsmono.ttf", "JetBrains Mono"),
)


def _register_fonts() -> set[str]:
    """Load the bundled OFL faces for this process; return the ones that loaded."""
    loaded: set[str] = set()
    if sys.platform != "win32":
        return loaded
    FR_PRIVATE = 0x10
    for filename, family in _FONT_FILES:
        path = _FONT_DIR / filename
        if not path.exists():
            continue
        try:
            count = ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0)
        except Exception:
            continue
        if count:
            loaded.add(family)
    return loaded


_BUNDLED = _register_fonts()

if "Inter" in _BUNDLED:
    DISPLAY_FONT = "Inter Light"     # h1, light display
    HEADLINE_FONT = "Inter"          # h2, section heads
    WORDMARK_FONT = "Inter"          # lockup
else:
    DISPLAY_FONT = "Segoe UI Light"
    HEADLINE_FONT = "Segoe UI Light"
    WORDMARK_FONT = "Segoe UI"

FONT = "Inter" if "Inter" in _BUNDLED else "Segoe UI"
MONO = "JetBrains Mono" if "JetBrains Mono" in _BUNDLED else "Consolas"

# Enumerated type ramp, px at a 16px root. Sizes are negative in Tk = pixels,
# so the ramp lands exactly where the design system puts it.
TYPE = {
    "hero": 40,
    "display": 34,
    "headline": 28,
    "title": 18,
    "lead": 15,
    "body": 14,
    "small": 13,
    "label": 12,
    "micro": 11,
    "mono": 11,
    "mono_lg": 12,
    "wordmark": 17,
}

# Spacing scale
GAP_XS = 8
GAP_SM = 16
GAP_MD = 24
GAP_LG = 32
GAP_XL = 48


def font(size: int = TYPE["body"], weight: str = "normal",
         family: str = FONT) -> tuple:
    """Inter (or the fallback) at a px size from the ramp."""
    return (family, -size, weight)


def display_font(size: int = TYPE["hero"]) -> tuple:
    """Inter Light — hero and major statements."""
    return (DISPLAY_FONT, -size, "normal")


def headline_font(size: int = TYPE["headline"]) -> tuple:
    """Inter — section anchors."""
    return (HEADLINE_FONT, -size, "normal")


def mono_font(size: int = TYPE["mono"], weight: str = "normal") -> tuple:
    return (MONO, -size, weight)


def blend(color_a: str, color_b: str, t: float) -> str:
    """Linear blend of two #rrggbb colors, t=0 -> a, t=1 -> b."""
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t)
                                   for i in range(3))


def label(parent, text: str = "", *, size: int = TYPE["small"],
          weight: str = "normal", fg: str = TEXT, bg: str = SURFACE,
          family: str = FONT, anchor: str = "w", **kwargs) -> tk.Label:
    """A tk.Label pre-wired to the palette (no theme background surprises)."""
    return tk.Label(parent, text=text, font=(family, -size, weight), fg=fg, bg=bg,
                    anchor=anchor, justify="left", bd=0, highlightthickness=0,
                    **kwargs)


def divider(parent, bg: str = BORDER) -> tk.Frame:
    """One-pixel horizontal rule."""
    return tk.Frame(parent, bg=bg, height=1)


def seam(parent, width: int = 56, bg: str = ACCENT) -> tk.Frame:
    """Short accent seam used as a structural brand mark."""
    return tk.Frame(parent, bg=bg, height=1, width=width)


def tag(parent, text: str, *, kind: str = "accent", bg: str = SURFACE) -> tk.Label:
    """Mono brand tag. kind: accent | quiet | live | danger."""
    palette = {
        "accent": (ON_ACCENT, ACCENT_FILL),
        "quiet": (MUTED, SURFACE_3),
        "live": (LIVE_TEXT, LIVE_WASH),
        "danger": (DANGER_TEXT, DANGER_WASH),
    }
    fg, fill = palette.get(kind, palette["quiet"])
    return tk.Label(parent, text=text, font=mono_font(TYPE["micro"], "bold"),
                    fg=fg, bg=fill, padx=8, pady=3, bd=0, highlightthickness=0)


def chip(parent, text: str, *, fg: str = MUTED, bg: str = SURFACE_3) -> tk.Label:
    """Quiet tag — kept as the call-site name used across the pages."""
    return tk.Label(parent, text=text, font=mono_font(TYPE["micro"]),
                    fg=fg, bg=bg, padx=9, pady=4, bd=0, highlightthickness=0)


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Install the light ttk styles used by buttons, inputs and tables."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.option_add("*Font", font(TYPE["small"]))
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_WASH)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_RICH)
    root.option_add("*Text.selectBackground", ACCENT_WASH)
    root.option_add("*Text.selectForeground", INK)

    style.configure(".", background=BG, foreground=TEXT,
                    font=font(TYPE["small"]))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT,
                    font=font(TYPE["small"]))

    # -- buttons -----------------------------------------------------------
    # Primary: blue fill, black ink, hairline outline.
    style.configure("Accent.TButton", background=ACCENT_FILL, foreground=ON_ACCENT,
                    bordercolor=ACCENT_HAIRLINE, lightcolor=ACCENT_FILL,
                    darkcolor=ACCENT_FILL, borderwidth=1, focusthickness=0,
                    focuscolor=ACCENT, relief="solid", padding=(18, 10),
                    font=(FONT, -TYPE["small"], "bold"), anchor="center")
    style.map("Accent.TButton",
              background=[("pressed", "#a8cff1"), ("active", "#cfe6fa"),
                          ("disabled", SURFACE_3)],
              foreground=[("disabled", MUTE_DEEP)],
              bordercolor=[("pressed", ACCENT), ("active", ACCENT_DEEP),
                           ("disabled", BORDER)],
              lightcolor=[("active", "#cfe6fa"), ("disabled", SURFACE_3)],
              darkcolor=[("active", "#cfe6fa"), ("disabled", SURFACE_3)])

    # Secondary: white paper, blue hairline, blue text.
    style.configure("Ghost.TButton", background=SURFACE, foreground=ACCENT,
                    bordercolor=ACCENT_HAIRLINE, lightcolor=SURFACE,
                    darkcolor=SURFACE, borderwidth=1, focusthickness=0,
                    focuscolor=ACCENT, relief="solid", padding=(14, 8),
                    font=(FONT, -TYPE["small"], "normal"), anchor="center")
    style.map("Ghost.TButton",
              background=[("pressed", ACCENT_WASH), ("active", ACCENT_WASH_SOFT),
                          ("disabled", SURFACE)],
              foreground=[("active", ACCENT_RICH), ("disabled", MUTE_DEEP)],
              bordercolor=[("active", ACCENT), ("disabled", BORDER_SOFT)])

    # Destructive: red hairline and red text on paper.
    style.configure("Danger.TButton", background=SURFACE, foreground=DANGER_TEXT,
                    bordercolor="#efc9bf", lightcolor=SURFACE, darkcolor=SURFACE,
                    borderwidth=1, focusthickness=0, focuscolor=DANGER,
                    relief="solid", padding=(14, 8),
                    font=(FONT, -TYPE["small"], "normal"), anchor="center")
    style.map("Danger.TButton",
              background=[("active", DANGER_WASH), ("pressed", "#fbdfd8")],
              foreground=[("active", "#8e2f1c")],
              bordercolor=[("active", DANGER)])

    # Quiet: mono micro chrome for card headers and log tools.
    style.configure("Small.TButton", background=SURFACE, foreground=MUTED,
                    bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
                    borderwidth=1, focusthickness=0, focuscolor=ACCENT,
                    relief="solid", padding=(10, 5),
                    font=mono_font(TYPE["micro"]), anchor="center")
    style.map("Small.TButton",
              background=[("active", SURFACE_2)],
              foreground=[("active", INK)],
              bordercolor=[("active", ACCENT_HAIRLINE)])

    # -- inputs ------------------------------------------------------------
    style.configure("TEntry", fieldbackground=SURFACE, foreground=INK,
                    insertcolor=ACCENT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(10, 6),
                    font=font(TYPE["small"]))
    style.map("TEntry",
              bordercolor=[("focus", ACCENT)],
              lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)],
              fieldbackground=[("disabled", SURFACE_2)],
              foreground=[("disabled", MUTE_DEEP)])

    style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE_2,
                    foreground=INK, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(10, 6),
                    font=font(TYPE["small"]))
    style.map("TCombobox",
              fieldbackground=[("readonly", SURFACE)],
              foreground=[("readonly", INK)],
              selectbackground=[("readonly", SURFACE)],
              selectforeground=[("readonly", INK)],
              bordercolor=[("focus", ACCENT), ("active", ACCENT_HAIRLINE)],
              arrowcolor=[("active", ACCENT), ("focus", ACCENT)])

    style.configure("TSpinbox", fieldbackground=SURFACE, foreground=INK,
                    arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=(8, 5),
                    font=font(TYPE["small"]))
    style.map("TSpinbox",
              bordercolor=[("focus", ACCENT)],
              arrowcolor=[("active", ACCENT)])

    style.configure("TCheckbutton", background=SURFACE, foreground=MUTED,
                    focuscolor=SURFACE, indicatorbackground=SURFACE,
                    indicatorforeground=ACCENT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER,
                    font=font(TYPE["small"]))
    style.map("TCheckbutton",
              background=[("active", SURFACE)],
              foreground=[("active", INK)],
              indicatorbackground=[("selected", ACCENT_WASH), ("active", SURFACE_2)],
              indicatorforeground=[("selected", ACCENT)])

    # -- tables ------------------------------------------------------------
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, borderwidth=0, rowheight=30,
                    bordercolor=SURFACE, lightcolor=SURFACE, darkcolor=SURFACE,
                    font=font(TYPE["small"]))
    style.configure("Treeview.Heading", background=SURFACE_2, foreground=FAINT,
                    borderwidth=0, relief="flat", padding=(10, 8),
                    bordercolor=SURFACE_2, lightcolor=SURFACE_2,
                    darkcolor=SURFACE_2,
                    font=mono_font(TYPE["micro"], "bold"))
    style.map("Treeview.Heading", background=[("active", SURFACE_3)],
              bordercolor=[("active", SURFACE_3)],
              foreground=[("active", MUTED)])
    style.map("Treeview", background=[("selected", ACCENT_WASH)],
              foreground=[("selected", INK)],
              bordercolor=[("focus", SURFACE)],
              lightcolor=[("focus", SURFACE)],
              darkcolor=[("focus", SURFACE)])

    # -- scrollbars --------------------------------------------------------
    style.configure("Slim.Vertical.TScrollbar", gripcount=0,
                    background=SURFACE_3, darkcolor=SURFACE, lightcolor=SURFACE,
                    troughcolor=FIELD, bordercolor=FIELD, arrowcolor=FAINT,
                    arrowsize=12, width=10)
    style.map("Slim.Vertical.TScrollbar",
              background=[("active", BORDER)])

    style.configure("TPanedwindow", background=BG)

    # Classic scrollbar fallback (e.g. Text widgets created by other code).
    root.option_add("*Scrollbar.background", SURFACE_3)
    root.option_add("*Scrollbar.troughColor", BG)
    root.option_add("*Scrollbar.activeBackground", BORDER)
    root.option_add("*Scrollbar.borderWidth", 0)

    return style
