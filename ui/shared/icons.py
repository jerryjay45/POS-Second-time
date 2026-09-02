"""
ui/shared/icons.py
Small hand-painted glyph helpers shared across the app.

Qt stylesheets can point `image:` at a file, but not at anything drawn at
runtime — so widgets that need a crisp checkmark, X, etc. inside a QSS rule
have to render it to a real file once and reference that path. Doing this
here (rather than duplicating a QPainter routine in every dialog) keeps the
glyph identical everywhere it's used and means changing the accent color
regenerates it automatically the next time a screen calls apply_theme().
"""
import os
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon


def draw_icon(kind: str, color: str, size: int = 19) -> QIcon:
    """Return a QIcon with a small hand-painted glyph (currently just
    'clear', an X). Buttons that need an icon like this shouldn't depend
    on a Unicode dingbat + font fallback chain — that can still render
    off-center or at the wrong weight even once symbol_font() has found a
    family that has the glyph at all, since font metrics (ascent/descent,
    advance width) vary per family and don't guarantee the glyph sits
    visually centered in a fixed-size button."""
    scale = 4
    s = size * scale
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(s * 0.14)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    if kind == "clear":
        m = s * 0.24
        p.drawLine(int(m), int(m), int(s - m), int(s - m))
        p.drawLine(int(s - m), int(m), int(m), int(s - m))
    p.end()
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
    return QIcon(pm)


def checkmark_png(color: str = "#FFFFFF", size: int = 16) -> str:
    """Return a cached, forward-slash file path to a checkmark PNG in
    `color`, for use as a QSS `image:url(...)` value (e.g. on a checked
    QCheckBox::indicator). Cached per (color, size) in the OS temp dir."""
    safe = f"{color.lstrip('#').upper()}_{size}"
    path = os.path.join(tempfile.gettempdir(), f"pos_checkmark_{safe}.png")
    if os.path.exists(path):
        return path.replace("\\", "/")

    scale = 8
    s = size * scale
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(s * 0.16)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(int(s * 0.20), int(s * 0.52), int(s * 0.42), int(s * 0.75))
    p.drawLine(int(s * 0.42), int(s * 0.75), int(s * 0.82), int(s * 0.26))
    p.end()
    pm.save(path, "PNG")
    return path.replace("\\", "/")
