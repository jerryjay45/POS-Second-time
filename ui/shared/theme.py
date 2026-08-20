"""
ui/shared/theme.py
Multi-theme system for Merchant POS Systems.

Adding a new theme:
  1. Add a dict entry to THEMES below — only override what changes.
  2. That's it. Call apply_theme("your_theme_name") at startup or from settings.

Available themes:  amber (default) | blue | green | high_contrast
"""

from __future__ import annotations

# ── Base palette (shared across all themes — functional colors) ───────────────
_BASE = {
    # Status colors — same in every theme
    "RED":          "#A32D2D",
    "RED_LIGHT":    "#FCEBEB",
    "RED_BORDER":   "#F09595",
    "GREEN":        "#1E7A3E",
    "GREEN_LIGHT":  "#E6F9EE",
    "GREEN_BORDER": "#A3D9B5",
    "PURPLE":       "#7A3B9A",
    "PURPLE_LIGHT": "#F3EAF8",
    "BLUE":         "#2A6DB5",
    "BLUE_LIGHT":   "#EAF3FF",
    "WHITE":        "#FFFFFF",
    "MAIN_FONT":    "Inter",
    "MONO_FONT":    "DM Mono",
}

# ── Theme definitions ─────────────────────────────────────────────────────────
# Each theme only needs to define what differs from _BASE.
# Required keys: ACCENT, ACCENT_DARK, ACCENT_DARKER, ACCENT_LIGHT,
#                ACCENT_LIGHTEST, ACCENT_BG,
#                DARK, DARK_2, DARK_3, DARK_4, DARK_CARD,
#                WARM_WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT

THEMES: dict[str, dict] = {

    # ── Amber (default) ───────────────────────────────────────────────
    "amber": {
        "ACCENT":          "#EF9F27",
        "ACCENT_DARK":     "#BA7517",
        "ACCENT_DARKER":   "#633806",
        "ACCENT_LIGHT":    "#FAC775",
        "ACCENT_LIGHTEST": "#FAEEDA",
        "ACCENT_BG":       "#FEF3DC",
        "DARK":            "#0D0D0D",
        "DARK_2":          "#1A1A1A",
        "DARK_3":          "#222222",
        "DARK_4":          "#2E2E2E",
        "DARK_CARD":       "#1C1C1A",
        "WARM_WHITE":      "#FFFFFF",
        "BORDER":          "#C8C3B8",
        "BORDER_LIGHT":    "#E2DDD3",
        "MUTED":           "#6B6860",
        "SUBTLE":          "#3D3C39",
        "LABEL_TEXT":      "#4A4845",
    },

    # ── Dark blue ─────────────────────────────────────────────────────
    "blue": {
        "ACCENT":          "#3B82F6",
        "ACCENT_DARK":     "#1D4ED8",
        "ACCENT_DARKER":   "#1E3A8A",
        "ACCENT_LIGHT":    "#93C5FD",
        "ACCENT_LIGHTEST": "#DBEAFE",
        "ACCENT_BG":       "#EFF6FF",
        "DARK":            "#0A0F1E",
        "DARK_2":          "#151D30",
        "DARK_3":          "#1E2A42",
        "DARK_4":          "#263550",
        "DARK_CARD":       "#0F1829",
        "WARM_WHITE":      "#FFFFFF",
        "BORDER":          "#94A3B8",
        "BORDER_LIGHT":    "#CBD5E1",
        "MUTED":           "#475569",
        "SUBTLE":          "#334155",
        "LABEL_TEXT":      "#374151",
    },

    # ── Green ─────────────────────────────────────────────────────────
    "green": {
        "ACCENT":          "#16A34A",
        "ACCENT_DARK":     "#15803D",
        "ACCENT_DARKER":   "#14532D",
        "ACCENT_LIGHT":    "#86EFAC",
        "ACCENT_LIGHTEST": "#DCFCE7",
        "ACCENT_BG":       "#F0FDF4",
        "DARK":            "#052E16",
        "DARK_2":          "#14532D",
        "DARK_3":          "#166534",
        "DARK_4":          "#15803D",
        "DARK_CARD":       "#052E16",
        "WARM_WHITE":      "#F0FDF4",
        "BORDER":          "#BBF7D0",
        "BORDER_LIGHT":    "#D1FAE5",
        "MUTED":           "#6EE7B7",
        "SUBTLE":          "#34D399",
        "LABEL_TEXT":      "#059669",
    },

    # ── High contrast (accessibility) ─────────────────────────────────
    "high_contrast": {
        "ACCENT":          "#FFDD00",
        "ACCENT_DARK":     "#CCA800",
        "ACCENT_DARKER":   "#665400",
        "ACCENT_LIGHT":    "#FFE966",
        "ACCENT_LIGHTEST": "#FFFACC",
        "ACCENT_BG":       "#FFFEEE",
        "DARK":            "#000000",
        "DARK_2":          "#0A0A0A",
        "DARK_3":          "#111111",
        "DARK_4":          "#1A1A1A",
        "DARK_CARD":       "#000000",
        "WARM_WHITE":      "#FFFFFF",
        "BORDER":          "#000000",
        "BORDER_LIGHT":    "#333333",
        "MUTED":           "#444444",
        "SUBTLE":          "#222222",
        "LABEL_TEXT":      "#333333",
    },
}

# ── Fallback module-level names (overwritten by apply_theme) ─────────────────────
BLUE_LIGHT = "#EAF3FF"
BLUE       = "#2A6DB5"

# ── Active palette (module-level, updated by apply_theme) ─────────────────────
_active: dict = {}


def apply_theme(name: str = "amber") -> dict:
    """
    Merge base + theme into _active and expose as module-level names.
    Returns the full palette dict.
    Call once at startup: apply_theme(db_config.get("theme", "amber"))
    """
    global _active
    theme = THEMES.get(name, THEMES["amber"])
    _active = {**_BASE, **theme}

    # Expose as legacy module-level names so existing code doesn't break
    g = globals()
    # Accent aliases
    g["AMBER"]          = _active["ACCENT"]
    g["AMBER_DARK"]     = _active["ACCENT_DARK"]
    g["AMBER_DARKER"]   = _active["ACCENT_DARKER"]
    g["AMBER_LIGHT"]    = _active["ACCENT_LIGHT"]
    g["AMBER_LIGHTEST"] = _active["ACCENT_LIGHTEST"]
    g["AMBER_BG"]       = _active["ACCENT_BG"]
    # Neutral
    g["DARK"]           = _active["DARK"]
    g["DARK_2"]         = _active["DARK_2"]
    g["DARK_3"]         = _active["DARK_3"]
    g["DARK_4"]         = _active["DARK_4"]
    g["DARK_CARD"]      = _active["DARK_CARD"]
    g["WARM_WHITE"]     = _active["WARM_WHITE"]
    g["WHITE"]          = _active["WHITE"]
    g["BORDER"]         = _active["BORDER"]
    g["BORDER_LIGHT"]   = _active["BORDER_LIGHT"]
    g["MUTED"]          = _active["MUTED"]
    g["SUBTLE"]         = _active.get("SUBTLE", _active["MUTED"])
    g["LABEL_TEXT"]     = _active["LABEL_TEXT"]
    # Status (unchanged)
    g["RED"]            = _active["RED"]
    g["RED_LIGHT"]      = _active["RED_LIGHT"]
    g["RED_BORDER"]     = _active["RED_BORDER"]
    g["GREEN"]          = _active["GREEN"]
    g["GREEN_LIGHT"]    = _active["GREEN_LIGHT"]
    g["GREEN_BORDER"]   = _active["GREEN_BORDER"]
    g["PURPLE"]         = _active["PURPLE"]
    g["PURPLE_LIGHT"]   = _active["PURPLE_LIGHT"]
    g["BLUE"]           = _active["BLUE"]
    g["BLUE_LIGHT"]     = _active["BLUE_LIGHT"]
    g["BLUE_LIGHT"]     = _active["BLUE_LIGHT"]
    g["MAIN_FONT"]      = _active["MAIN_FONT"]

    return _active


def get_stylesheet() -> str:
    """
    Returns the full Qt stylesheet using the currently active theme.
    Call app.setStyleSheet(get_stylesheet()) at startup or after theme change.
    """
    A  = _active.get("ACCENT",       "#EF9F27")
    AD = _active.get("ACCENT_DARK",  "#BA7517")
    AL = _active.get("ACCENT_LIGHTEST", "#FAEEDA")
    AB = _active.get("ACCENT_BG",    "#FEF3DC")
    D  = _active.get("DARK",         "#111111")
    D2 = _active.get("DARK_2",       "#1E1E1E")
    D4 = _active.get("DARK_4",       "#2A2A2A")
    DC = _active.get("DARK_CARD",    "#2C2C2A")
    WW = _active.get("WARM_WHITE",   "#F8F6F1")
    W  = _active.get("WHITE",        "#FFFFFF")
    B  = _active.get("BORDER",       "#E2DDD3")
    BL = _active.get("BORDER_LIGHT", "#F1EFE8")
    M  = _active.get("MUTED",        "#B4B2A9")
    LT = _active.get("LABEL_TEXT",   "#888780")
    F  = _active.get("MAIN_FONT",    "Inter")

    return f"""
QWidget {{
    font-family: "{F}", "Segoe UI", sans-serif;
    font-size: 14px;
    font-weight: 500;
    color: {DC};
    background-color: {WW};
}}
QMainWindow, QDialog {{ background-color: {WW}; }}

QPushButton {{
    background-color: {A}; color: white; border: none;
    border-radius: 8px; padding: 7px 18px;
    font-size: 13px; font-weight: 700;
}}
QPushButton:hover   {{ background-color: {AD}; }}
QPushButton:pressed {{ background-color: {_active.get("ACCENT_DARKER","#633806")}; }}
QPushButton:disabled {{ background-color: {M}; color: white; }}

QPushButton[flat="true"] {{
    background-color: transparent; color: {_active.get("SUBTLE",M)};
    border: 1.5px solid {B}; font-weight: 600;
}}
QPushButton[flat="true"]:hover {{
    border-color: {A}; color: {A}; background-color: {AL};
}}
QPushButton[danger="true"] {{ background-color: {_active["RED"]}; }}
QPushButton[danger="true"]:hover {{ background-color: #7A1E1E; }}
QPushButton[dark="true"] {{ background-color: {DC}; }}
QPushButton[dark="true"]:hover {{ background-color: #444441; }}

QLineEdit {{
    background-color: {W}; border: 2px solid {B};
    border-radius: 7px; padding: 5px 12px;
    font-size: 13px; font-weight: 500; color: {DC};
    min-height: 20px;
}}
QLineEdit:focus {{ border-color: {A}; border-width: 2px; }}

QComboBox {{
    background-color: {W}; border: 2px solid {B};
    border-radius: 7px; padding: 5px 12px;
    font-size: 13px; font-weight: 500; color: {DC};
    min-height: 20px;
}}
QComboBox:focus {{ border-color: {A}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {W}; border: 1.5px solid {B};
    selection-background-color: {AL}; selection-color: {DC};
    font-size: 13px; font-weight: 500;
    padding: 2px;
}}

QTableWidget {{
    background-color: {W}; gridline-color: {BL};
    border: none; font-size: 13px; font-weight: 500;
}}
QTableWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {BL}; color: {DC}; }}
QTableWidget::item:selected {{ background-color: {AB}; color: {DC}; }}
QHeaderView::section {{
    background-color: {D}; color: {A};
    font-size: 12px; font-weight: 700;
    padding: 8px 12px; border: none;
    border-right: 1px solid {D4};
}}

QScrollBar:vertical {{
    background: {WW}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {B}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {M}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QLabel {{ background: transparent; font-size: 13px; font-weight: 500; color: {DC}; }}

QTabBar::tab {{
    background: {W}; color: {LT};
    border: none; border-bottom: 2px solid transparent;
    padding: 11px 18px; font-size: 13px; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {DC}; border-bottom: 2px solid {A}; font-weight: 700; }}
QTabBar::tab:hover {{ color: {DC}; }}
QTabWidget::pane {{ border: none; border-top: 1.5px solid {B}; }}

QCheckBox {{ font-size: 13px; font-weight: 500; spacing: 8px; color: {DC}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 2px solid {B}; border-radius: 4px; background: {W};
}}
QCheckBox::indicator:checked {{
    background-color: {A}; border-color: {A};
}}

QSpinBox, QDoubleSpinBox {{
    background-color: {W}; border: 2px solid {B};
    border-radius: 7px; padding: 5px 12px;
    font-size: 13px; font-weight: 500; color: {DC};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {A}; }}

QFrame#topbar {{ background-color: {D}; border-bottom: 1px solid {D4}; }}
QFrame#sidebar {{ background-color: {D2}; border-right: 1px solid {D4}; }}
QFrame#totalsPanel {{ background-color: {D2}; border-left: 1px solid {D4}; }}
QFrame#bottombar {{ background-color: {D2}; border-top: 1px solid {D4}; }}
QStatusBar {{ background-color: {D}; color: {M}; font-size: 12px; font-weight: 500; }}
"""


def theme_names() -> list[str]:
    """Returns list of available theme names for the manager settings UI."""
    return list(THEMES.keys())


# ── Auto-apply on import (reads saved preference or defaults to amber) ─────────
def _init():
    try:
        from core.db_config import get as cfg_get
        name = cfg_get("theme", "amber")
    except Exception:
        name = "amber"
    apply_theme(name)


_init()
