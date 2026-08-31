"""
ui/shared/checkbox.py
A checkbox that actually looks checked.

Every ad hoc QCheckBox stylesheet in this app (price_tag_tab, product_dialog,
the Business tab's permission toggles, the printer/PostgreSQL toggles, and
even the app-wide default in theme.get_stylesheet()) does the same thing:
`QCheckBox::indicator:checked{background:AMBER}` — filling the box with a
flat color and nothing else. There's no checkmark glyph at all, so "checked"
just reads as "this square turned orange," which is easy to misread at a
glance and doesn't work for anyone who can't rely on color alone.

This module draws a real check glyph into the box, and spells out the
hover/disabled states explicitly instead of leaving them to native/OS
rendering (the same "no OS default" pass already applied to stock_tab.py).

Usage:
    from ui.shared.checkbox import make_checkbox
    cb = make_checkbox("Enable PostgreSQL sync", checked=False)

Or, to style an existing QCheckBox in place:
    from ui.shared.checkbox import checkbox_style
    my_checkbox.setStyleSheet(checkbox_style())
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox

from ui.shared import theme
from ui.shared.icons import checkmark_png


def checkbox_style(size: int = 17, font_size: int = 12) -> str:
    check = checkmark_png("#FFFFFF", size=size)
    return (
        f"QCheckBox{{color:{theme.DARK_CARD};font-size:{font_size}px;"
        f"font-weight:500;spacing:8px;outline:none;}}"
        f"QCheckBox::indicator{{width:{size}px;height:{size}px;"
        f"border:1.5px solid {theme.BORDER};border-radius:4px;background:{theme.WHITE};}}"
        f"QCheckBox::indicator:hover{{border-color:{theme.AMBER};}}"
        f"QCheckBox::indicator:checked{{background:{theme.AMBER};"
        f"border-color:{theme.AMBER};image:url({check});}}"
        f"QCheckBox::indicator:checked:hover{{background:{theme.AMBER_DARK};"
        f"border-color:{theme.AMBER_DARK};}}"
        f"QCheckBox::indicator:disabled{{background:{theme.BORDER_LIGHT};"
        f"border-color:{theme.BORDER_LIGHT};}}"
        f"QCheckBox:disabled{{color:{theme.MUTED};}}"
    )


def make_checkbox(label: str, checked: bool = False, size: int = 17,
                   font_size: int = 12) -> QCheckBox:
    cb = QCheckBox(label)
    cb.setChecked(checked)
    cb.setCursor(Qt.CursorShape.PointingHandCursor)
    cb.setStyleSheet(checkbox_style(size, font_size))
    return cb
