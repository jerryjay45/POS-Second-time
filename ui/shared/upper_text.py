"""
ui/shared/upper_text.py
A small multi-line text box that forces CAPITALS as you type - the multi-line
counterpart of the single-line "uppercase" inputs used on the Business Info form
and in the setup wizard.

Unlike a naive setPlainText(text.upper()) it keeps the cursor where it was, so
fixing a typo in the middle of an address doesn't throw the cursor to the end.
"""

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QPlainTextEdit


def make_upper_textbox(placeholder: str = "", lines: int = 3, style: str = "") -> QPlainTextEdit:
    """A QPlainTextEdit `lines` rows tall (it scrolls if more are typed) that uppercases
    as the user types. `style` is the caller's own stylesheet, so the box matches the
    form it is used in; give it ~6px vertical padding."""
    box = QPlainTextEdit()
    box.setPlaceholderText(placeholder)
    box.setTabChangesFocus(True)                    # Tab moves on instead of inserting a tab
    if style:
        box.setStyleSheet(style)
    box.setFixedHeight(QFontMetrics(box.font()).lineSpacing() * lines + 22)

    def _force_upper():
        text, upper = box.toPlainText(), box.toPlainText().upper()
        if text == upper:
            return
        pos = box.textCursor().position()
        box.blockSignals(True)
        box.setPlainText(upper)
        cursor = box.textCursor()
        cursor.setPosition(min(pos, len(upper)))
        box.setTextCursor(cursor)
        box.blockSignals(False)

    box.textChanged.connect(_force_upper)
    return box
