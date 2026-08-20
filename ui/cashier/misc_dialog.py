"""
ui/cashier/misc_dialog.py
Miscellaneous item dialog — add a one-off item to the cart
without a barcode or product DB entry.

Fields: description, qty, price, GCT applicable toggle.
Returns a cart-compatible item dict on accept.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QSpinBox, QCheckBox, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui  import QDoubleValidator

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST,
    DARK, DARK_CARD, WHITE, WARM_WHITE,
    BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, GREEN,
)
from core.db_config import gct_rate


class MiscDialog(QDialog):
    """
    Add a miscellaneous one-off item to the cart.
    On accept, call result_item() to get the cart dict.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Miscellaneous Item")
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(f"background:{WHITE};")
        self._gct_rate = gct_rate()
        self._result   = None
        self._build_ui()

    # ================================================================
    # UI
    # ================================================================

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QFrame(); hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{DARK};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 0, 18, 0)
        t = QLabel("✱  Miscellaneous Item")
        t.setStyleSheet("color:white;font-size:14px;font-weight:700;")
        x = QPushButton("✕"); x.setFixedSize(28, 28)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            "QPushButton{background:transparent;color:#888;border:none;font-size:16px;}"
            "QPushButton:hover{color:white;}"
        )
        x.clicked.connect(self.reject)
        hl.addWidget(t); hl.addStretch(); hl.addWidget(x)
        lay.addWidget(hdr)

        # Body
        body = QWidget(); body.setStyleSheet(f"background:{WHITE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 18, 20, 18)
        bl.setSpacing(14)

        # Description
        bl.addWidget(self._lbl("Description"))
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("e.g. Custom cake, One-off repair, Special order…")
        self.desc_input.setFixedHeight(40)
        self.desc_input.setStyleSheet(self._inp())
        self.desc_input.textChanged.connect(self._validate)
        bl.addWidget(self.desc_input)

        # Qty + Price row
        row = QHBoxLayout(); row.setSpacing(12)

        qty_col = QVBoxLayout(); qty_col.setSpacing(6)
        qty_col.addWidget(self._lbl("Qty"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setMinimum(1); self.qty_spin.setMaximum(9999)
        self.qty_spin.setValue(1); self.qty_spin.setFixedHeight(40)
        self.qty_spin.setStyleSheet(f"""
            QSpinBox{{background:{WHITE};color:{DARK_CARD};
            border:1px solid {BORDER};border-radius:8px;
            padding:0 10px;font-size:14px;font-weight:600;}}
            QSpinBox:focus{{border-color:{AMBER};}}
            QSpinBox::up-button,QSpinBox::down-button{{width:18px;background:{WARM_WHITE};border:none;}}
        """)
        self.qty_spin.valueChanged.connect(self._update_preview)
        qty_col.addWidget(self.qty_spin)

        price_col = QVBoxLayout(); price_col.setSpacing(6)
        price_col.addWidget(self._lbl("Unit Price"))
        price_wrap = QHBoxLayout(); price_wrap.setSpacing(0)
        dollar = QLabel("$"); dollar.setFixedWidth(22)
        dollar.setStyleSheet(f"color:{MUTED};font-size:16px;font-weight:600;background:transparent;")
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("0.00")
        self.price_input.setFixedHeight(40)
        self.price_input.setValidator(QDoubleValidator(0, 999999, 2))
        self.price_input.setStyleSheet(self._inp())
        self.price_input.textChanged.connect(self._validate)
        self.price_input.textChanged.connect(self._update_preview)
        price_wrap.addWidget(dollar)
        price_wrap.addWidget(self.price_input)
        price_col.addLayout(price_wrap)

        row.addLayout(qty_col, stretch=1)
        row.addLayout(price_col, stretch=2)
        bl.addLayout(row)

        # GCT toggle
        gct_box = QFrame()
        gct_box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        gl = QHBoxLayout(gct_box); gl.setContentsMargins(14, 10, 14, 10)
        self.gct_check = QCheckBox("GCT Applicable")
        self.gct_check.setChecked(True)
        self.gct_check.setStyleSheet(f"""
            QCheckBox{{color:{DARK_CARD};font-size:13px;font-weight:500;}}
            QCheckBox::indicator{{width:18px;height:18px;
            border:1.5px solid {BORDER};border-radius:4px;background:{WHITE};}}
            QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}
        """)
        self.gct_check.stateChanged.connect(self._update_preview)
        self.gct_rate_lbl = QLabel(f"({self._gct_rate*100:.1f}%)")
        self.gct_rate_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;background:transparent;")
        gl.addWidget(self.gct_check)
        gl.addWidget(self.gct_rate_lbl)
        gl.addStretch()
        bl.addWidget(gct_box)

        # Preview
        self.preview_frame = QFrame()
        self.preview_frame.setStyleSheet(
            f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};border-radius:8px;"
        )
        pl = QVBoxLayout(self.preview_frame)
        pl.setContentsMargins(14, 10, 14, 10); pl.setSpacing(4)
        prev_title = QLabel("Preview")
        prev_title.setStyleSheet(f"color:{AMBER_DARK};font-size:10px;font-weight:700;"
                                  "text-transform:uppercase;letter-spacing:0.5px;background:transparent;")
        self.preview_lbl = QLabel("—")
        self.preview_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:600;background:transparent;")
        self.preview_lbl.setWordWrap(True)
        pl.addWidget(prev_title); pl.addWidget(self.preview_lbl)
        bl.addWidget(self.preview_frame)

        # Error label
        self.error_lbl = QLabel("")
        self.error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_lbl.setStyleSheet(f"color:{RED};font-size:11px;min-height:16px;background:transparent;")
        bl.addWidget(self.error_lbl)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        cancel = QPushButton("Cancel"); cancel.setFixedHeight(40)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton{{background:{DARK_CARD};color:white;border:none;
            border-radius:20px;font-size:13px;font-weight:600;padding:0 20px;}}
            QPushButton:hover{{background:#444;}}
        """)
        cancel.clicked.connect(self.reject)

        self.add_btn = QPushButton("✚  Add to Cart")
        self.add_btn.setFixedHeight(40)
        self.add_btn.setEnabled(False)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:white;border:none;
            border-radius:20px;font-size:13px;font-weight:700;padding:0 20px;}}
            QPushButton:hover:enabled{{background:{AMBER_DARK};}}
            QPushButton:disabled{{background:{MUTED};color:white;}}
        """)
        self.add_btn.clicked.connect(self._confirm)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self.add_btn, stretch=1)
        bl.addLayout(btn_row)

        lay.addWidget(body)
        self.desc_input.setFocus()

    # ================================================================
    # LOGIC
    # ================================================================

    def _validate(self):
        desc  = self.desc_input.text().strip()
        price = self.price_input.text().strip()
        ok = bool(desc) and bool(price)
        try:
            if price: float(price)
        except ValueError:
            ok = False
        self.add_btn.setEnabled(ok)
        self.error_lbl.setText("" if ok or not desc else "Enter a valid price.")

    def _update_preview(self):
        desc  = self.desc_input.text().strip() or "—"
        qty   = self.qty_spin.value()
        try:    price = float(self.price_input.text() or 0)
        except: price = 0.0
        gct_amt = round(price * self._gct_rate, 2) if self.gct_check.isChecked() else 0.0
        total   = round((price + gct_amt) * qty, 2)
        gct_str = f" + GCT ${gct_amt * qty:.2f}" if gct_amt else ""
        self.preview_lbl.setText(
            f"{desc}  ×{qty}  @  ${price:.2f}{gct_str}  =  ${total:.2f}"
        )

    def _confirm(self):
        desc  = self.desc_input.text().strip()
        qty   = self.qty_spin.value()
        try:    price = float(self.price_input.text())
        except: return
        gct_applicable = self.gct_check.isChecked()
        gct_amt = round(price * self._gct_rate, 2) if gct_applicable else 0.0
        total   = round((price + gct_amt) * qty, 2)

        self._result = {
            "id":               None,           # no product ID — one-off
            "barcode":          "MISC",
            "name":             f"[Misc] {desc}",
            "qty":              qty,
            "price":            price,
            "cost":             0.0,
            "gct":              gct_amt,
            "gct_applicable":   gct_applicable,
            "discount_applied": 0.0,
            "total":            total,
            "disc_level_id":    None,
            "disc_level2_id":   None,
        }
        self.accept()

    def result_item(self) -> dict | None:
        """Call after exec() returns Accepted."""
        return self._result

    # ================================================================
    # STYLE HELPERS
    # ================================================================

    def _inp(self) -> str:
        return (
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:8px;"
            f"padding:0 12px;font-size:14px;font-weight:500;}}"
            f"QLineEdit:focus{{border-color:{AMBER};}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
        )

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{LABEL_TEXT};font-size:11px;font-weight:600;"
            "text-transform:uppercase;letter-spacing:0.4px;"
        )
        return l
