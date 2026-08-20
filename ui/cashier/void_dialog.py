"""
ui/cashier/void_dialog.py
Supervisor-authorised item removal dialog.

Used for three cases:
  1. Remove single item (✕ button)    — one item pre-checked
  2. Remove Items button               — all items pre-checked
  3. Clear Cart button                 — all items pre-checked

Supervisor or manager must enter their password to authorise.
On accept: returns list of removed items + authorising user info.
No transaction record is created.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QWidget,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui  import QColor

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST,
    DARK, DARK_CARD, WHITE, WARM_WHITE,
    BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, RED_BORDER, GREEN,
)
from core.db_users import get_users, authenticate


class VoidDialog(QDialog):
    """
    Supervisor-authorised item removal dialog.

    Parameters
    ----------
    cart        : list of cart item dicts
    pre_select  : list of indices to pre-check (None = all)
    mode        : 'remove' | 'void'
    parent      : parent widget
    """

    def __init__(self, cart: list, pre_select: list = None,
                 mode: str = "void", parent=None):
        super().__init__(parent)
        self.cart          = cart
        self.pre_select    = pre_select if pre_select is not None else list(range(len(cart)))
        self.mode          = mode
        self.voided_items  = []       # filled on accept
        self.authorised_by = None     # full_name of authoriser
        self.authorised_id = None     # user id of authoriser

        title = "Remove Item" if mode == "remove" else "Remove Items"
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet(f"background:{WHITE};")
        self._build_ui(title)

    # ================================================================
    # UI BUILD
    # ================================================================

    def _build_ui(self, title: str):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr = QFrame(); hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{DARK};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 0, 18, 0)
        t = QLabel(f"⊘  {title}")
        t.setStyleSheet(f"color:{RED_LIGHT};font-size:14px;font-weight:700;")
        x = QPushButton("✕"); x.setFixedSize(28, 28)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet("QPushButton{background:transparent;color:#888;border:none;font-size:16px;}QPushButton:hover{color:white;}")
        x.clicked.connect(self.reject)
        hl.addWidget(t); hl.addStretch(); hl.addWidget(x)
        lay.addWidget(hdr)

        # ── Subtitle ──────────────────────────────────────────────────
        sub_frame = QFrame()
        sub_frame.setStyleSheet(f"background:{RED_LIGHT};border-bottom:1px solid {RED_BORDER};")
        sl = QHBoxLayout(sub_frame); sl.setContentsMargins(18, 10, 18, 10)
        sub = QLabel(
            "Select the item to remove. A supervisor or manager must authorise."
            if self.mode == "remove" else
            "Select items to remove. A supervisor or manager must authorise."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{RED};font-size:12px;background:transparent;")
        sl.addWidget(sub)
        lay.addWidget(sub_frame)

        # ── Body ──────────────────────────────────────────────────────
        body = QWidget(); body.setStyleSheet(f"background:{WHITE};")
        bl = QVBoxLayout(body); bl.setContentsMargins(18, 14, 18, 14); bl.setSpacing(12)

        # Cart table with checkboxes
        self.item_table = QTableWidget()
        self.item_table.setColumnCount(5)
        self.item_table.setHorizontalHeaderLabels(["", "Product", "Qty", "Price", "Total"])
        hh = self.item_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in [2, 3, 4]:
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.item_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.verticalHeader().setVisible(False)
        self.item_table.setShowGrid(False)
        self.item_table.setMinimumHeight(80)
        self.item_table.setStyleSheet(f"""
            QTableWidget{{background:{WHITE};border:1px solid {BORDER};
            border-radius:8px;font-size:12px;}}
            QTableWidget::item{{padding:6px 8px;border-bottom:1px solid {BORDER_LIGHT};
            color:{DARK_CARD};}}
            QHeaderView::section{{background:{DARK};color:{AMBER};font-size:11px;
            font-weight:700;padding:6px 8px;border:none;
            border-right:1px solid #2a2a2a;}}
        """)
        bl.addWidget(self.item_table)

        # Void total display
        self._void_total_lbl = QLabel("")
        self._void_total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._void_total_lbl.setStyleSheet(f"color:{RED};font-size:13px;font-weight:700;")
        bl.addWidget(self._void_total_lbl)
        self._update_void_total()

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
        bl.addWidget(div)

        # Auth section
        auth_lbl = QLabel("Supervisor / Manager Password")
        auth_lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;"
                                "text-transform:uppercase;letter-spacing:0.4px;")
        bl.addWidget(auth_lbl)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter supervisor or manager password…")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setFixedHeight(42)
        self.password_input.setStyleSheet(f"""
            QLineEdit{{background:{WARM_WHITE};color:{DARK_CARD};
            border:1.5px solid {BORDER};border-radius:8px;
            padding:0 14px;font-size:14px;}}
            QLineEdit:focus{{border-color:{RED};background:{WHITE};}}
        """)
        self.password_input.returnPressed.connect(self._authorise)
        bl.addWidget(self.password_input)

        # Error label — shown as a banner when wrong password entered
        self.error_frame = QFrame()
        self.error_frame.setVisible(False)
        self.error_frame.setStyleSheet(
            f"background:{RED_LIGHT};border:1px solid {RED_BORDER};"
            "border-radius:7px;"
        )
        ef_lay = QHBoxLayout(self.error_frame)
        ef_lay.setContentsMargins(12, 8, 12, 8)
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet(
            f"color:{RED};font-size:12px;font-weight:600;background:transparent;"
        )
        self.error_lbl.setWordWrap(True)
        ef_lay.addWidget(self.error_lbl)
        bl.addWidget(self.error_frame)

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

        self.confirm_btn = QPushButton(
            "⊘  Authorise Remove"
        )
        self.confirm_btn.setFixedHeight(40)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet(f"""
            QPushButton{{background:{RED_LIGHT};color:{RED};
            border:1.5px solid {RED_BORDER};border-radius:20px;
            font-size:13px;font-weight:700;padding:0 20px;}}
            QPushButton:hover{{background:{RED};color:white;}}
            QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};
            border-color:{BORDER};}}
        """)
        self.confirm_btn.setAutoDefault(False)
        self.confirm_btn.setDefault(False)
        self.confirm_btn.clicked.connect(self._authorise)
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self.confirm_btn, stretch=1)
        bl.addLayout(btn_row)

        lay.addWidget(body)
        self._populate_table()  # called after confirm_btn exists
        self._fit_table_to_rows()
        self._update_void_total()
        self.adjustSize()
        self.password_input.setFocus()

    # ================================================================
    # TABLE
    # ================================================================

    def _populate_table(self):
        self._checkboxes = []
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter

        self.item_table.setRowCount(len(self.cart))
        for row, item in enumerate(self.cart):
            self.item_table.setRowHeight(row, 36)

            # Checkbox
            chk_w = QWidget(); chk_l = QHBoxLayout(chk_w)
            chk_l.setContentsMargins(4, 0, 4, 0)
            chk_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(row in self.pre_select)
            chk.setStyleSheet(f"""
                QCheckBox::indicator{{width:16px;height:16px;
                border:1.5px solid {BORDER};border-radius:3px;background:{WHITE};}}
                QCheckBox::indicator:checked{{background:{RED};border-color:{RED};}}
            """)
            chk.stateChanged.connect(self._update_void_total)
            chk_l.addWidget(chk)
            self.item_table.setCellWidget(row, 0, chk_w)
            self._checkboxes.append(chk)

            line_total = item.get("total", item["price"] * item["qty"])

            def cell(t, color=DARK_CARD, align=None):
                c = QTableWidgetItem(str(t))
                c.setForeground(QColor(color))
                if align: c.setTextAlignment(align)
                return c

            self.item_table.setItem(row, 1, cell(item["name"]))
            self.item_table.setItem(row, 2, cell(str(item["qty"]), MUTED, C))
            self.item_table.setItem(row, 3, cell(f"${item['price']:.2f}", AMBER_DARK, R))
            self.item_table.setItem(row, 4, cell(f"${line_total:.2f}", RED, R))

    def keyPressEvent(self, event):
        """Block Escape and Enter from closing the dialog unexpectedly."""
        from PyQt6.QtCore import Qt as _Qt
        if event.key() in (_Qt.Key.Key_Escape,):
            return  # ignore Escape — use Cancel button
        if event.key() in (_Qt.Key.Key_Return, _Qt.Key.Key_Enter):
            # Only act on Enter if focus is on password field
            if self.password_input.hasFocus():
                self._authorise()
            return
        super().keyPressEvent(event)

    def _fit_table_to_rows(self):
        """Resize table height to exactly fit all rows + header."""
        hh = self.item_table.horizontalHeader().height()
        rows_h = sum(
            self.item_table.rowHeight(r)
            for r in range(self.item_table.rowCount())
        )
        padding = 4
        self.item_table.setFixedHeight(hh + rows_h + padding)

    def _update_void_total(self):
        if not hasattr(self, "_checkboxes") or not hasattr(self, "confirm_btn"): return
        total = 0.0
        for i, item in enumerate(self.cart):
            if self._checkboxes[i].isChecked():
                total += item.get("total", item["price"] * item["qty"])
        count = sum(1 for c in self._checkboxes if c.isChecked())
        if hasattr(self, "_void_total_lbl"):
            if count:
                self._void_total_lbl.setText(
                    f"Removing {count} item{'s' if count != 1 else ''}  —  ${total:.2f}"
                )
            else:
                self._void_total_lbl.setText("No items selected")
        if hasattr(self, "confirm_btn"):
            self.confirm_btn.setEnabled(count > 0)

    # ================================================================
    # AUTHORISATION
    # ================================================================

    def _authorise(self):
        password = self.password_input.text().strip()
        if not password:
            self._show_error("Please enter a supervisor or manager password.")
            return

        # Check which items are selected
        selected = [i for i, c in enumerate(self._checkboxes) if c.isChecked()]
        if not selected:
            self._show_error("Please select at least one item.")
            return

        # Authenticate — must be supervisor or manager
        auth_user = self._check_supervisor_password(password)
        if not auth_user:
            self._show_error("Incorrect password or insufficient permissions. Please try again.")
            self.password_input.clear()
            self.password_input.setFocus()
            return

        # Build voided items list
        self.voided_items  = [self.cart[i] for i in selected]
        self.authorised_by = auth_user["full_name"]
        self.authorised_id = auth_user["id"]
        self.accept()

    def _show_error(self, msg: str):
        """Display error banner and shake the password field."""
        self.error_lbl.setText(msg)
        self.error_frame.setVisible(True)
        # Flash password border red briefly
        self.password_input.setStyleSheet(
            self.password_input.styleSheet().replace(
                f"border:1.5px solid {BORDER}", f"border:1.5px solid {RED}"
            )
        )
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.password_input.setStyleSheet(
            self.password_input.styleSheet().replace(
                f"border:1.5px solid {RED}", f"border:1.5px solid {BORDER}"
            )
        ))

    def _check_supervisor_password(self, password: str) -> dict | None:
        """
        Check if the password belongs to an active supervisor or manager.
        Returns the user dict or None.
        """
        users = get_users(role="supervisor") + get_users(role="manager")
        for u in users:
            if not u.get("is_active"): continue
            result = authenticate(u["username"], password)
            if result and result["id"] == u["id"]:
                return result
        return None
