"""
ui/cashier/checkout_dialog.py
Checkout dialog — adapted from prototype.
Cash / Card / Split payment, live change display,
quick amounts, receipt save, reprint hook.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui  import QDoubleValidator

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_LIGHT,
    DARK, DARK_CARD, WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT, RED, RED_LIGHT, RED_BORDER,
    GREEN, GREEN_LIGHT, GREEN_BORDER,
)
from core.db_checkout import save_receipt
from core.db_users    import add_session_sales
from core.db_config   import gct_rate, checkout_quick_amounts


class CheckoutDialog(QDialog):

    def __init__(self, cart: list, user: dict, session_id: int, parent=None):
        super().__init__(parent)
        self.cart         = cart
        self.user         = user
        self.session_id   = session_id
        self._method      = "cash"
        self.change_given = 0.0
        self.last_txn_id  = None

        # Pre-calculate totals
        self.subtotal  = round(sum(i["price"] * i["qty"] for i in cart), 2)
        self.gct_total = round(sum(i["gct"]   * i["qty"] for i in cart), 2)
        self.discount  = round(sum(i.get("discount_applied", 0.0) * i["qty"] for i in cart), 2)
        self.total     = round(self.subtotal + self.gct_total - self.discount, 2)
        self._gct_rate = gct_rate()

        self.setWindowTitle("Checkout")
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(f"background:{WHITE};")
        self._build_ui()
        self._update_change()
        self.cash_input.setFocus()

    # ================================================================
    # UI BUILD
    # ================================================================

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(48)
        hdr.setStyleSheet(f"background:{DARK};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 0, 18, 0)
        title = QLabel("🧾  Checkout")
        title.setStyleSheet("color:white;font-size:14px;font-weight:700;")
        close = QPushButton("✕")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{background:transparent;color:#888;border:none;font-size:16px;}"
            "QPushButton:hover{color:white;}"
        )
        close.clicked.connect(self.reject)
        hl.addWidget(title); hl.addStretch(); hl.addWidget(close)
        lay.addWidget(hdr)

        # ── Totals strip ──────────────────────────────────────────────
        strip = QFrame()
        strip.setStyleSheet(f"background:{AMBER_LIGHTEST};border-bottom:1px solid #e8e0cc;")
        sl = QHBoxLayout(strip); sl.setContentsMargins(0, 0, 0, 0)
        for lbl_txt, val_txt, grand in [
            ("Subtotal",  f"${self.subtotal:.2f}",  False),
            ("GCT",       f"${self.gct_total:.2f}", False),
            ("Discount",  f"${self.discount:.2f}",  False),
            ("Total Due", f"${self.total:.2f}",      True),
        ]:
            item = QFrame(); il = QVBoxLayout(item)
            il.setContentsMargins(0, 8, 0, 8); il.setSpacing(1)
            l = QLabel(lbl_txt); l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet("font-size:10px;color:#BA7517;font-weight:600;")
            v = QLabel(val_txt); v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.setStyleSheet(
                f"font-size:{'15' if grand else '13'}px;font-weight:700;"
                f"color:{'#2C2C2A' if grand else '#633806'};"
                "font-family:'DM Mono',monospace;"
            )
            il.addWidget(l); il.addWidget(v)
            sl.addWidget(item, stretch=1)
        lay.addWidget(strip)

        # ── Body ──────────────────────────────────────────────────────
        body = QFrame()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(12)

        # Method tabs
        tab_row = QHBoxLayout(); tab_row.setSpacing(6)
        self._tab_cash  = self._method_tab("💵  Cash")
        self._tab_card  = self._method_tab("💳  Card")
        self._tab_split = self._method_tab("⇄  Split")
        self._tab_cash.clicked.connect(lambda: self._select_method("cash"))
        self._tab_card.clicked.connect(lambda: self._select_method("card"))
        self._tab_split.clicked.connect(lambda: self._select_method("split"))
        tab_row.addWidget(self._tab_cash)
        tab_row.addWidget(self._tab_card)
        tab_row.addWidget(self._tab_split)
        bl.addLayout(tab_row)

        # Amount label
        self._amount_lbl = QLabel("Cash Tendered")
        self._amount_lbl.setStyleSheet(
            f"font-size:11px;font-weight:600;color:{LABEL_TEXT};"
            "text-transform:uppercase;letter-spacing:0.4px;"
        )
        bl.addWidget(self._amount_lbl)

        # Single amount input (cash/card)
        self._single_widget = QFrame()
        sw = QVBoxLayout(self._single_widget)
        sw.setContentsMargins(0,0,0,0); sw.setSpacing(8)

        amt_row = QHBoxLayout(); amt_row.setSpacing(0)
        dollar = QLabel("$")
        dollar.setStyleSheet(f"font-size:20px;font-weight:600;color:{MUTED};")
        self.cash_input = QLineEdit()
        self.cash_input.setPlaceholderText("0.00")
        self.cash_input.setFixedHeight(50)
        self.cash_input.setValidator(QDoubleValidator(0, 999999, 2))
        self.cash_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.cash_input.setStyleSheet(f"""
            QLineEdit{{background:#FAFAF8;color:{DARK_CARD};
            border:2px solid {AMBER};border-radius:9px;
            padding:0 12px;font-size:24px;font-weight:700;
            font-family:'DM Mono',monospace;}}
            QLineEdit:focus{{background:white;border-color:{AMBER_DARK};}}
        """)
        self.cash_input.textChanged.connect(self._update_change)
        self.cash_input.returnPressed.connect(self._confirm_payment)
        amt_row.addWidget(dollar); amt_row.addWidget(self.cash_input)
        sw.addLayout(amt_row)

        # Quick amount buttons
        self._quick_widget = QFrame()
        qw = QHBoxLayout(self._quick_widget)
        qw.setContentsMargins(0,0,0,0); qw.setSpacing(6)
        for amt in checkout_quick_amounts()[:4]:
            b = QPushButton(f"${amt:.0f}")
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton{{background:white;border:1px solid {BORDER};
                border-radius:14px;font-size:11px;font-weight:500;color:{LABEL_TEXT};}}
                QPushButton:hover{{border-color:{AMBER};color:{AMBER};background:{AMBER_LIGHTEST};}}
            """)
            b.clicked.connect(lambda _, a=amt: self._set_quick(a))
            qw.addWidget(b)
        sw.addWidget(self._quick_widget)
        bl.addWidget(self._single_widget)

        # Split inputs (cash + card)
        self._split_widget = QFrame()
        self._split_widget.setVisible(False)
        spl = QHBoxLayout(self._split_widget)
        spl.setContentsMargins(0,0,0,0); spl.setSpacing(10)

        for attr, lbl_txt in [("_split_cash","Cash"), ("_split_card","Card")]:
            col = QFrame(); cl = QVBoxLayout(col)
            cl.setContentsMargins(0,0,0,0); cl.setSpacing(5)
            lbl = QLabel(lbl_txt)
            lbl.setStyleSheet(
                f"font-size:11px;font-weight:600;color:{LABEL_TEXT};"
                "text-transform:uppercase;"
            )
            wrap = QFrame(); wl = QHBoxLayout(wrap)
            wl.setContentsMargins(0,0,0,0); wl.setSpacing(0)
            p = QLabel("$"); p.setStyleSheet(f"font-size:13px;color:{MUTED};")
            inp = QLineEdit("0.00"); inp.setFixedHeight(38)
            inp.setValidator(QDoubleValidator(0, 999999, 2))
            inp.setAlignment(Qt.AlignmentFlag.AlignRight)
            inp.setStyleSheet(f"""
                QLineEdit{{border:1px solid {BORDER};border-radius:7px;
                font-size:15px;font-weight:600;color:{DARK_CARD};
                background:white;padding:0 8px;font-family:'DM Mono',monospace;}}
                QLineEdit:focus{{border-color:{AMBER};}}
            """)
            inp.textChanged.connect(self._update_change)
            setattr(self, attr, inp)
            wl.addWidget(p); wl.addWidget(inp, stretch=1)
            cl.addWidget(lbl); cl.addWidget(wrap)
            spl.addWidget(col)
        bl.addWidget(self._split_widget)

        # Change / owed display
        self._change_frame = QFrame()
        self._change_frame.setFixedHeight(46)
        self._change_frame.setStyleSheet(
            f"background:{GREEN_LIGHT};border:1px solid {GREEN_BORDER};border-radius:8px;"
        )
        cfl = QHBoxLayout(self._change_frame)
        cfl.setContentsMargins(14, 0, 14, 0)
        self._change_lbl = QLabel("Change Due")
        self._change_lbl.setStyleSheet(f"font-size:13px;font-weight:500;color:{GREEN};")
        self._change_val = QLabel("$0.00")
        self._change_val.setStyleSheet(
            f"font-size:20px;font-weight:800;color:{GREEN};"
            "font-family:'DM Mono',monospace;"
        )
        cfl.addWidget(self._change_lbl); cfl.addStretch(); cfl.addWidget(self._change_val)
        bl.addWidget(self._change_frame)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(40)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton{{background:{DARK};color:white;border:none;
            border-radius:8px;font-size:13px;font-weight:600;}}
            QPushButton:hover{{background:#333;}}
        """)
        cancel.clicked.connect(self.reject)

        self._confirm_btn = QPushButton("Confirm Payment")
        self._confirm_btn.setFixedHeight(40)
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_btn.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:white;border:none;
            border-radius:8px;font-size:13px;font-weight:700;}}
            QPushButton:hover:enabled{{background:{AMBER_DARK};}}
            QPushButton:disabled{{background:#D3D1C7;color:white;}}
        """)
        self._confirm_btn.clicked.connect(self._confirm_payment)

        btn_row.addWidget(cancel)
        btn_row.addWidget(self._confirm_btn, stretch=1)
        bl.addLayout(btn_row)

        lay.addWidget(body)
        self._select_method("cash")

    # ================================================================
    # METHOD SWITCHING
    # ================================================================

    def _method_tab(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setFixedHeight(34)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _select_method(self, method: str):
        self._method = method
        for tab, m in [(self._tab_cash,"cash"),(self._tab_card,"card"),(self._tab_split,"split")]:
            active = (m == method)
            tab.setChecked(active)
            tab.setStyleSheet(f"""
                QPushButton{{background:{''+AMBER if active else WHITE};
                color:{'white' if active else LABEL_TEXT};
                border:{'none' if active else f'1px solid {BORDER}'};
                border-radius:7px;font-size:12px;font-weight:{'600' if active else '500'};}}
                QPushButton:hover{{border-color:{AMBER};color:{'white' if active else AMBER};}}
            """)

        is_split = method == "split"
        is_card  = method == "card"

        self._single_widget.setVisible(not is_split)
        self._split_widget.setVisible(is_split)
        self._quick_widget.setVisible(not is_split and not is_card)
        self._amount_lbl.setText("Card Amount" if is_card else "Cash Tendered")
        self._change_frame.setVisible(not is_card)

        if is_card:
            self.cash_input.setText(f"{self.total:.2f}")

        self._update_change()

    # ================================================================
    # CHANGE CALCULATION
    # ================================================================

    def _update_change(self):
        if self._method == "split":
            try:    cash = float(self._split_cash.text() or 0)
            except: cash = 0
            try:    card = float(self._split_card.text() or 0)
            except: card = 0
            tendered = cash + card
        else:
            try:    tendered = float(self.cash_input.text() or 0)
            except: tendered = 0

        if self._method == "card":
            self._confirm_btn.setEnabled(tendered >= self.total)
            return

        change = round(tendered - self.total, 2)

        if tendered == 0:
            self._change_val.setText("$0.00")
            self._change_val.setStyleSheet(
                f"font-size:20px;font-weight:800;color:{MUTED};"
                "font-family:'DM Mono',monospace;"
            )
            self._change_lbl.setStyleSheet(f"font-size:13px;font-weight:500;color:{MUTED};")
            self._change_frame.setStyleSheet(
                f"background:#f5f5f5;border:1px solid {BORDER};border-radius:8px;"
            )
            self._confirm_btn.setEnabled(False)
        elif change < 0:
            self._change_val.setText(f"-${abs(change):.2f}")
            self._change_val.setStyleSheet(
                f"font-size:20px;font-weight:800;color:{RED};"
                "font-family:'DM Mono',monospace;"
            )
            self._change_lbl.setStyleSheet(f"font-size:13px;font-weight:500;color:{RED};")
            self._change_frame.setStyleSheet(
                f"background:{RED_LIGHT};border:1px solid {RED_BORDER};border-radius:8px;"
            )
            self._confirm_btn.setEnabled(False)
        else:
            self._change_val.setText(f"${change:.2f}")
            self._change_val.setStyleSheet(
                f"font-size:20px;font-weight:800;color:{GREEN};"
                "font-family:'DM Mono',monospace;"
            )
            self._change_lbl.setStyleSheet(f"font-size:13px;font-weight:500;color:{GREEN};")
            self._change_frame.setStyleSheet(
                f"background:{GREEN_LIGHT};border:1px solid {GREEN_BORDER};border-radius:8px;"
            )
            self._confirm_btn.setEnabled(True)

    def _set_quick(self, amt: float):
        self.cash_input.setText(f"{amt:.2f}")
        self.cash_input.setFocus()

    # ================================================================
    # CONFIRM PAYMENT
    # ================================================================

    def _confirm_payment(self):
        try:
            if self._method == "cash":
                tendered = float(self.cash_input.text() or 0)
                card_amt = None
            elif self._method == "card":
                tendered = self.total
                card_amt = self.total
            else:
                tendered = float(self._split_cash.text() or 0)
                card_amt = float(self._split_card.text() or 0)
                tendered = tendered  # cash portion only for change calc
        except ValueError:
            QMessageBox.warning(self, "Invalid Amount", "Please enter a valid amount.")
            return

        if self._method == "cash" and tendered < self.total:
            QMessageBox.warning(
                self, "Insufficient Cash",
                f"Cash (${tendered:.2f}) is less than total (${self.total:.2f}).\n"
                f"Shortage: ${self.total - tendered:.2f}"
            )
            self.cash_input.selectAll(); self.cash_input.setFocus()
            return

        if self._method == "split":
            combined = tendered + (card_amt or 0)
            if combined < self.total:
                QMessageBox.warning(
                    self, "Insufficient Amount",
                    f"Combined amount (${combined:.2f}) is less than total (${self.total:.2f})."
                )
                return
            change = round(combined - self.total, 2)
        elif self._method == "card":
            change = 0.0
        else:
            change = round(tendered - self.total, 2)

        self.change_given = change
        success = self._save_transaction(tendered, card_amt, change)

        if success:
            self._confirm_btn.setText(f"✓  Receipt #{self.last_txn_id}")
            self._confirm_btn.setStyleSheet(f"""
                QPushButton{{background:#1E7A3E;color:white;border:none;
                border-radius:8px;font-size:13px;font-weight:700;}}
            """)
            self._confirm_btn.setEnabled(False)
            QTimer.singleShot(1000, self.accept)
        else:
            QMessageBox.critical(self, "Error", "Failed to save transaction. Please try again.")

    # ================================================================
    # SAVE TO DB
    # ================================================================

    def _save_transaction(self, cash_tendered: float,
                          card_amount: float, change: float) -> bool:
        try:
            items = []
            for ci in self.cart:
                items.append({
                    "product_id":      ci.get("id"),
                    "barcode":         ci.get("barcode", ""),
                    "product_name":    ci["name"],
                    "quantity":        ci["qty"],
                    "unit_price":      ci["price"],
                    "discount_amount": ci.get("discount_applied", 0.0) * ci["qty"],
                    "gct_amount":      ci["gct"] * ci["qty"],
                    "line_total":      ci["total"],
                })

            receipt = save_receipt(
                user_id         = self.user["id"],
                session_id      = self.session_id,
                items           = items,
                subtotal        = self.subtotal,
                gct_amount      = self.gct_total,
                discount_amount = self.discount,
                total           = self.total,
                payment_method  = self._method,
                cash_tendered   = cash_tendered if self._method in ("cash","split") else None,
                card_amount     = card_amount,
                change_given    = max(0, change),
            )

            self.last_txn_id = receipt["receipt_number"]
            add_session_sales(self.session_id, self.total)

            # Decrement stock if tracking is enabled
            from core.db_config import get_bool
            if get_bool("stock_tracking", False):
                from core.db_products import decrement_stock
                for ci in self.cart:
                    if ci.get("id"):
                        decrement_stock(ci["id"], ci["qty"])

            # Auto-print receipt (non-blocking)
            try:
                from utils.print_manager import print_receipt
                print_receipt(receipt, parent=self)
            except Exception as e:
                print(f"[Print] Receipt print skipped: {e}")

            return True

        except Exception as e:
            print(f"[Checkout] Save error: {e}")
            return False

    # ================================================================
    # HELPERS
    # ================================================================

    def _summary_row(self, label: str, value: str, bold=False):
        row = QFrame(); row.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(row); lay.setContentsMargins(0,0,0,0)
        lc = DARK_CARD if bold else LABEL_TEXT
        vc = DARK_CARD if bold else AMBER_DARK
        fs = "15" if bold else "13"
        fw = "700" if bold else "400"
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{lc};font-size:{fs}px;font-weight:{fw};background:transparent;")
        val = QLabel(value); val.setAlignment(Qt.AlignmentFlag.AlignRight)
        val.setStyleSheet(f"color:{vc};font-size:{fs}px;font-weight:{fw};background:transparent;")
        lay.addWidget(lbl); lay.addWidget(val)
        return row
