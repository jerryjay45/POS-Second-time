"""
ui/supervisor/void_refund_tab.py
Void / Refund / Exchange tab — clean ground-up implementation.

Layout:
  Left panel  — searchable receipt list with date range + status filter
  Right panel — receipt detail (items table + totals) + action panel
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QLineEdit, QPushButton, QComboBox, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QTextEdit, QCheckBox, QMessageBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QFont

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_4, DARK_CARD,
    WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN, GREEN_LIGHT,
)
from core.db_checkout import (
    get_receipts, get_receipt_by_id,
    void_receipt, refund_receipt, exchange_receipt,
    get_refunds_for_receipt, get_refund_items,
    get_receipts_with_refund_summary,
)
from core.db_users import get_user_by_id, authenticate
from utils.print_manager import print_void, print_refund


# ── Helpers ───────────────────────────────────────────────────────────────────

def _div():
    d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
    d.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
    return d

def _lbl(text, color=None, size=12, bold=False):
    l = QLabel(text)
    style = f"color:{color or DARK_CARD};font-size:{size}px;font-weight:{'700' if bold else '500'};"
    if bold: style += "font-weight:700;"
    l.setStyleSheet(style)
    return l

INPUT_STYLE = (
    f"QLineEdit,QTextEdit{{background:{WHITE};color:{DARK_CARD};"
    f"border:2px solid {BORDER};border-radius:7px;"
    f"padding:0 10px;font-size:13px;font-weight:500;}}"
    f"QLineEdit:focus,QTextEdit:focus{{border-color:{AMBER};}}"
)
COMBO_STYLE = (
    f"QComboBox{{background:{WHITE};color:{DARK_CARD};"
    f"border:2px solid {BORDER};border-radius:7px;padding:0 10px;"
    f"font-size:13px;font-weight:500;}}"
    f"QComboBox:focus{{border-color:{AMBER};}}"
    f"QComboBox::drop-down{{border:none;width:20px;}}"
)
def _btn(text, color=AMBER, text_color="white", h=34, outlined=False):
    b = QPushButton(text); b.setFixedHeight(h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if outlined:
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{color};"
            f"border:1.5px solid {color};border-radius:7px;"
            f"font-size:12px;font-weight:700;padding:0 14px;}}"
            f"QPushButton:hover{{background:{color};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{MUTED};}}"
        )
    else:
        b.setStyleSheet(
            f"QPushButton{{background:{color};color:{text_color};border:none;"
            f"border-radius:7px;font-size:12px;font-weight:700;padding:0 14px;}}"
            f"QPushButton:hover{{opacity:0.85;}}"
            f"QPushButton:disabled{{background:{MUTED};color:white;}}"
        )
    return b


# ── VoidRefundTab ─────────────────────────────────────────────────────────────

class VoidRefundTab(QWidget):

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user             = user
        self._receipt         = None   # currently selected full receipt dict
        self._items_data      = []     # items of selected receipt
        self._build()
        self._load_list()

    # ═════════════════════════════════════════════════════════════════════
    # BUILD
    # ═════════════════════════════════════════════════════════════════════

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(4)
        split.setStyleSheet(f"QSplitter::handle{{background:{BORDER};width:1px;}}")
        root.addWidget(split)

        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setSizes([420, 680])

    # ── Left: receipt list ────────────────────────────────────────────

    def _build_left(self):
        w = QWidget()
        w.setStyleSheet(f"background:{WHITE};border-right:1px solid {BORDER_LIGHT};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Search
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("🔍  Receipt # or cashier…")
        self.search_inp.setFixedHeight(34)
        self.search_inp.setStyleSheet(INPUT_STYLE)
        self.search_inp.setStyleSheet(INPUT_STYLE)
        self.search_inp.textChanged.connect(self._load_list)
        lay.addWidget(self.search_inp)

        # Date range (optional)
        from PyQt6.QtWidgets import QCheckBox
        date_row = QHBoxLayout(); date_row.setSpacing(6)
        self.date_chk = QCheckBox("Date filter")
        self.date_chk.setChecked(False)
        self.date_chk.toggled.connect(self._on_date_toggled)
        date_row.addWidget(self.date_chk)
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_from.setCalendarPopup(True)
        self.date_from.setFixedHeight(30)
        self.date_from.setEnabled(False)
        self.date_from.dateChanged.connect(self._load_list)
        date_row.addWidget(self.date_from)
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setFixedHeight(30)
        self.date_to.setEnabled(False)
        self.date_to.dateChanged.connect(self._load_list)
        date_row.addWidget(self.date_to)
        date_row.addStretch()
        lay.addLayout(date_row)

        # Status filter
        self.status_combo = QComboBox()
        self.status_combo.setFixedHeight(34)
        self.status_combo.setStyleSheet(COMBO_STYLE)
        self.status_combo.addItems(["All Statuses","Completed","Voided","Refunded"])
        self.status_combo.currentIndexChanged.connect(self._load_list)
        lay.addWidget(self.status_combo)

        lay.addWidget(_div())

        # Receipt list table
        self.list_tbl = QTableWidget()
        self.list_tbl.setColumnCount(4)
        self.list_tbl.setHorizontalHeaderLabels(["Receipt","Date","Total","Status"])
        hh = self.list_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.list_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_tbl.verticalHeader().setVisible(False)
        self.list_tbl.setAlternatingRowColors(False)
        self.list_tbl.setStyleSheet(f"""
            QTableWidget{{background:{WHITE};border:none;
                gridline-color:{BORDER_LIGHT};font-size:13px;font-weight:500;}}
            QTableWidget::item{{padding:8px 12px;
                border-bottom:1px solid {BORDER_LIGHT};color:{DARK_CARD};}}
            QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}
            QHeaderView::section{{background:{DARK_CARD};color:{AMBER};
                font-size:12px;font-weight:700;padding:8px 12px;border:none;
                border-right:1px solid #333;}}
        """)
        self.list_tbl.itemSelectionChanged.connect(self._on_receipt_selected)
        lay.addWidget(self.list_tbl, stretch=1)

        self.list_count_lbl = _lbl("", MUTED, 11)
        lay.addWidget(self.list_count_lbl)
        return w

    # ── Right: detail + actions ───────────────────────────────────────

    def _build_right(self):
        w = QWidget()
        w.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # Receipt header info
        self.det_header = _lbl("Select a receipt from the list", MUTED, 13)
        lay.addWidget(self.det_header)

        # Items table
        self.items_tbl = QTableWidget()
        self.items_tbl.setColumnCount(5)
        self.items_tbl.setHorizontalHeaderLabels(["","Item","Qty","Price","Total"])
        ih = self.items_tbl.horizontalHeader()
        ih.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.items_tbl.setColumnWidth(0, 28)
        ih.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ih.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ih.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ih.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.items_tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.items_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items_tbl.verticalHeader().setVisible(False)
        self.items_tbl.setAlternatingRowColors(False)
        self.items_tbl.setStyleSheet(f"""
            QTableWidget{{background:{WHITE};border:1px solid {BORDER};
                border-radius:6px;gridline-color:{BORDER_LIGHT};
                font-size:13px;font-weight:500;}}
            QTableWidget::item{{padding:7px 10px;color:{DARK_CARD};
                border-bottom:1px solid {BORDER_LIGHT};}}
            QHeaderView::section{{background:{DARK_CARD};color:{AMBER};
                font-size:11px;font-weight:700;padding:7px 10px;border:none;
                border-right:1px solid #333;}}
        """)
        lay.addWidget(self.items_tbl, stretch=1)

        # Totals bar
        self.totals_lbl = _lbl("", DARK_CARD, 12, bold=True)
        self.totals_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.totals_lbl)

        lay.addWidget(_div())

        # ── Action panel ──────────────────────────────────────────────
        self.action_frame = QFrame()
        self.action_frame.setStyleSheet(
            f"background:{WARM_WHITE};border:1.5px solid {BORDER};border-radius:8px;"
        )
        af = QVBoxLayout(self.action_frame)
        af.setContentsMargins(14, 12, 14, 12)
        af.setSpacing(10)

        # Action type selector
        mode_row = QHBoxLayout(); mode_row.setSpacing(8)
        mode_row.addWidget(_lbl("Action:", bold=True))
        self.action_combo = QComboBox()
        self.action_combo.setFixedHeight(34)
        self.action_combo.setStyleSheet(COMBO_STYLE)
        self.action_combo.addItems([
            "— Select Action —",
            "Void (cancel entire sale)",
            "Full Refund (all items)",
            "Partial Refund (select items)",
            "Exchange (select items)",
        ])
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        mode_row.addWidget(self.action_combo, stretch=1)
        af.addLayout(mode_row)

        # Item selection (shown for partial refund + exchange)
        self.item_sel_frame = QFrame()
        self.item_sel_frame.setVisible(False)
        self.item_sel_frame.setStyleSheet(
            f"background:{WHITE};border:1px solid {BORDER};border-radius:6px;"
        )
        isl = QVBoxLayout(self.item_sel_frame)
        isl.setContentsMargins(10, 8, 10, 8); isl.setSpacing(4)
        isl.addWidget(_lbl("Select items:", bold=True))
        self.item_chk_layout = QVBoxLayout()
        self.item_chk_layout.setSpacing(3)
        isl.addLayout(self.item_chk_layout)
        self.item_sel_total = _lbl("", AMBER, 12, bold=True)
        isl.addWidget(self.item_sel_total)
        af.addWidget(self.item_sel_frame)

        # Exchange "for" field (shown for exchange)
        self.exchange_frame = QFrame()
        self.exchange_frame.setVisible(False)
        self.exchange_frame.setStyleSheet(
            f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};border-radius:6px;"
        )
        efl = QVBoxLayout(self.exchange_frame)
        efl.setContentsMargins(10, 8, 10, 8); efl.setSpacing(4)
        efl.addWidget(_lbl("Exchanged for (optional):", AMBER_DARK, bold=True))
        self.exchange_for_inp = QLineEdit()
        self.exchange_for_inp.setPlaceholderText("Describe replacement item(s)…")
        self.exchange_for_inp.setFixedHeight(32)
        self.exchange_for_inp.setStyleSheet(INPUT_STYLE)
        efl.addWidget(self.exchange_for_inp)
        af.addWidget(self.exchange_frame)

        # Reason
        reason_row = QHBoxLayout(); reason_row.setSpacing(8)
        reason_row.addWidget(_lbl("Reason:", bold=True))
        self.reason_inp = QLineEdit()
        self.reason_inp.setPlaceholderText("Required — enter reason…")
        self.reason_inp.setFixedHeight(32)
        self.reason_inp.setStyleSheet(INPUT_STYLE)
        reason_row.addWidget(self.reason_inp, stretch=1)
        af.addLayout(reason_row)

        # Supervisor auth row
        auth_row = QHBoxLayout(); auth_row.setSpacing(8)
        auth_row.addWidget(_lbl("Supervisor PIN/Password:", bold=True))
        self.auth_inp = QLineEdit()
        self.auth_inp.setPlaceholderText("Enter your password…")
        self.auth_inp.setEchoMode(QLineEdit.EchoMode.Password)
        self.auth_inp.setFixedHeight(32)
        self.auth_inp.setStyleSheet(INPUT_STYLE)
        self.auth_inp.returnPressed.connect(self._do_action)
        auth_row.addWidget(self.auth_inp, stretch=1)
        af.addLayout(auth_row)

        self.auth_err = _lbl("", RED, 11)
        af.addWidget(self.auth_err)

        # Confirm button
        self.confirm_btn = _btn("Confirm Action", AMBER)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._do_action)
        af.addWidget(self.confirm_btn)

        lay.addWidget(self.action_frame)

        # Status banner
        self.status_lbl = QLabel("")
        self.status_lbl.setVisible(False)
        self.status_lbl.setStyleSheet(
            f"color:{GREEN};font-size:12px;font-weight:700;"
            f"background:{GREEN_LIGHT};border:1px solid {GREEN};"
            f"border-radius:6px;padding:8px 12px;"
        )
        lay.addWidget(self.status_lbl)

        return w

    # ═════════════════════════════════════════════════════════════════════
    # LIST
    # ═════════════════════════════════════════════════════════════════════

    def _on_date_toggled(self, checked: bool):
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)
        self._load_list()

    def _load_list(self):
        search    = self.search_inp.text().strip()
        date_from = self.date_from.date().toString("yyyy-MM-dd") if self.date_chk.isChecked() else ""
        date_to   = self.date_to.date().toString("yyyy-MM-dd") if self.date_chk.isChecked() else ""
        status_t  = self.status_combo.currentText()
        status    = None if status_t == "All Statuses" else status_t.lower()

        receipts = get_receipts_with_refund_summary(
            status=status, search=search,
            date_from=date_from, date_to=date_to,
            limit=300,
        )

        STATUS_COLOR = {"completed": GREEN, "voided": RED, "refunded": AMBER}
        STATUS_BG    = {"voided": "#FFF0F0", "refunded": "#FFFBE6"}

        self.list_tbl.setRowCount(len(receipts))
        for i, r in enumerate(receipts):
            s   = r.get("status","completed")
            bg  = STATUS_BG.get(s)

            def cell(text, align=Qt.AlignmentFlag.AlignLeft):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                if bg: it.setBackground(QColor(bg))
                return it

            num = cell(r["receipt_number"])
            num.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list_tbl.setItem(i, 0, num)
            self.list_tbl.setItem(i, 1, cell(r["created_at"][:10]))
            self.list_tbl.setItem(i, 2, cell(
                f"${r['total']:.2f}", Qt.AlignmentFlag.AlignRight))

            # Status with partial/exchange badges
            parts = [s.capitalize()]
            if r.get("has_partial"):
                parts.append(f"(-${r['refunded_total']:.2f})")
            if r.get("has_exchange"):
                parts.append("(exch.)")
            sit = cell("  ".join(parts))
            sit.setForeground(QColor(STATUS_COLOR.get(s, MUTED)))
            if bg: sit.setBackground(QColor(bg))
            self.list_tbl.setItem(i, 3, sit)

        self.list_tbl.resizeRowsToContents()
        self.list_count_lbl.setText(f"{len(receipts)} receipt(s)")

    # ═════════════════════════════════════════════════════════════════════
    # RECEIPT SELECTION
    # ═════════════════════════════════════════════════════════════════════

    def _on_receipt_selected(self):
        rows = self.list_tbl.selectedItems()
        if not rows:
            return
        rid = self.list_tbl.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        receipt = get_receipt_by_id(rid)
        if not receipt:
            return

        self._receipt    = receipt
        self._items_data = receipt.get("items", [])

        # Header
        cashier = get_user_by_id(receipt["user_id"])
        cname   = cashier["full_name"] if cashier else "Unknown"
        self.det_header.setText(
            f"{receipt['receipt_number']}  ·  {receipt['created_at'][:16]}  "
            f"·  {cname}  ·  {receipt['payment_method'].capitalize()}"
        )
        self.det_header.setStyleSheet(
            f"color:{DARK_CARD};font-size:12px;font-weight:700;"
        )

        # Build refund/exchange history maps for highlighting
        refunds      = get_refunds_for_receipt(receipt["id"])
        refunded_ids = set()
        exchanged    = {}   # product_id -> exchange_for_name
        for rf in refunds:
            items = get_refund_items(rf["id"])
            for ri in items:
                pid = ri.get("product_id") or ri.get("product_name")
                if rf["refund_type"] in ("full","partial"):
                    refunded_ids.add(pid)
                elif rf["refund_type"] == "exchange":
                    exchanged[pid] = ri.get("exchange_for_name","")

        # Populate items table
        self.items_tbl.setRowCount(0)
        row_idx = 0
        for item in self._items_data:
            pid          = item.get("product_id") or item["product_name"]
            is_refunded  = pid in refunded_ids
            is_exchanged = pid in exchanged

            self.items_tbl.insertRow(row_idx)
            self.items_tbl.setRowHeight(row_idx, 30)

            # Col 0: status icon
            icon = ""
            if is_refunded:  icon = "↩"
            elif is_exchanged: icon = "⇄"
            icon_it = QTableWidgetItem(icon)
            icon_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_it.setForeground(QColor(RED if is_refunded else AMBER))
            self.items_tbl.setItem(row_idx, 0, icon_it)

            def _cell(text, align=Qt.AlignmentFlag.AlignLeft, strike=False):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                if is_refunded:
                    it.setBackground(QColor("#FFF0F0"))
                    it.setForeground(QColor(RED))
                    if strike:
                        f = it.font(); f.setStrikeOut(True); it.setFont(f)
                elif is_exchanged:
                    it.setBackground(QColor("#FFFBE6"))
                    it.setForeground(QColor(AMBER_DARK))
                return it

            R = Qt.AlignmentFlag.AlignRight
            C = Qt.AlignmentFlag.AlignHCenter
            self.items_tbl.setItem(row_idx, 1, _cell(item["product_name"], strike=True))
            self.items_tbl.setItem(row_idx, 2, _cell(item["quantity"], C))
            self.items_tbl.setItem(row_idx, 3, _cell(f"${item['unit_price']:.2f}", R))
            self.items_tbl.setItem(row_idx, 4, _cell(f"${item['line_total']:.2f}", R))
            row_idx += 1

            # Exchange note sub-row
            if is_exchanged and exchanged.get(pid):
                self.items_tbl.insertRow(row_idx)
                self.items_tbl.setRowHeight(row_idx, 20)
                note = QTableWidgetItem(f"   ⇄ {exchanged[pid]}")
                note.setForeground(QColor(AMBER_DARK))
                note.setBackground(QColor("#FFFBE6"))
                f = note.font(); f.setItalic(True); f.setPointSize(9); note.setFont(f)
                self.items_tbl.setItem(row_idx, 1, note)
                self.items_tbl.setSpan(row_idx, 1, 1, 3)
                row_idx += 1

        # Totals
        self.totals_lbl.setText(
            f"Subtotal: ${receipt['subtotal']:.2f}  ·  "
            f"GCT: ${receipt['gct_amount']:.2f}  ·  "
            f"Total: ${receipt['total']:.2f}  ·  "
            f"Status: {receipt['status'].capitalize()}"
        )

        # Reset action panel
        self._reset_action_panel()
        is_completed = (receipt["status"] == "completed")
        self.action_combo.setEnabled(is_completed)
        self.confirm_btn.setEnabled(False)

    # ═════════════════════════════════════════════════════════════════════
    # ACTION PANEL
    # ═════════════════════════════════════════════════════════════════════

    def _reset_action_panel(self):
        self.action_combo.setCurrentIndex(0)
        self.item_sel_frame.setVisible(False)
        self.exchange_frame.setVisible(False)
        self.reason_inp.clear()
        self.auth_inp.clear()
        self.auth_err.setText("")
        self.confirm_btn.setEnabled(False)
        self.status_lbl.setVisible(False)
        # clear item checkboxes
        while self.item_chk_layout.count():
            child = self.item_chk_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._item_chks = []

    def _on_action_changed(self, idx):
        self.auth_err.setText("")
        is_partial  = (idx == 3)   # Partial Refund
        is_exchange = (idx == 4)   # Exchange
        needs_items = is_partial or is_exchange

        self.item_sel_frame.setVisible(needs_items)
        self.exchange_frame.setVisible(is_exchange)

        if needs_items:
            self._build_item_checkboxes(is_exchange)

        self.confirm_btn.setEnabled(idx > 0)

    def _build_item_checkboxes(self, is_exchange: bool):
        # Clear existing
        while self.item_chk_layout.count():
            child = self.item_chk_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._item_chks = []

        for item in self._items_data:
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(0, 2, 0, 2); rl.setSpacing(8)

            chk = QCheckBox(item["product_name"])
            chk.setChecked(True)
            chk.setStyleSheet(
                f"QCheckBox{{color:{DARK_CARD};font-size:12px;}}"
                f"QCheckBox::indicator{{width:15px;height:15px;"
                f"border:1.5px solid {BORDER};border-radius:3px;background:{WHITE};}}"
                f"QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}"
            )
            chk.stateChanged.connect(self._update_item_total)
            rl.addWidget(chk, stretch=1)

            price_lbl = QLabel(f"${item['line_total']:.2f}")
            price_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
            rl.addWidget(price_lbl)

            self.item_chk_layout.addWidget(row_w)
            self._item_chks.append({
                "chk":          chk,
                "product_id":   item.get("product_id"),
                "product_name": item["product_name"],
                "unit_price":   item["unit_price"],
                "qty":          item["quantity"],
                "line_total":   item["line_total"],
            })

        self._update_item_total()

    def _update_item_total(self):
        total = sum(
            r["line_total"] for r in self._item_chks
            if r["chk"].isChecked()
        )
        self.item_sel_total.setText(f"Selected total: ${total:.2f}")

    # ═════════════════════════════════════════════════════════════════════
    # DO ACTION
    # ═════════════════════════════════════════════════════════════════════

    def _do_action(self):
        if not self._receipt:
            return

        reason = self.reason_inp.text().strip()
        if not reason:
            self.auth_err.setText("A reason is required.")
            return

        pw = self.auth_inp.text()
        if not pw:
            self.auth_err.setText("Enter your password to authorise.")
            return

        # Verify password
        user = authenticate(self.user["username"], pw)
        if user is None:
            self.auth_err.setText("Incorrect password. Try again.")
            self.auth_inp.clear(); self.auth_inp.setFocus()
            return

        if user["role"] not in ("supervisor","manager"):
            self.auth_err.setText("Only supervisors or managers can authorise this.")
            self.auth_inp.clear()
            return

        self.auth_err.setText("")
        idx = self.action_combo.currentIndex()

        if idx == 1:
            self._do_void(reason)
        elif idx == 2:
            self._do_full_refund(reason)
        elif idx == 3:
            self._do_partial_refund(reason)
        elif idx == 4:
            self._do_exchange(reason)

    def _do_void(self, reason: str):
        r = self._receipt
        if not void_receipt(r["id"], self.user["id"], reason):
            QMessageBox.critical(self, "Failed",
                "Could not void. Receipt may already be voided.")
            return
        self._post_action(f"Receipt {r['receipt_number']} voided.", RED)
        rec    = get_receipt_by_id(r["id"])
        refund = (get_refunds_for_receipt(r["id"]) or [{}])[0]
        self._maybe_restock(rec)
        print_void(rec, refund, self.user, self)

    def _do_full_refund(self, reason: str):
        r = self._receipt
        items = [
            {"product_id": it.get("product_id"), "product_name": it["product_name"],
             "qty": it["quantity"], "unit_price": it["unit_price"]}
            for it in self._items_data
        ]
        if not refund_receipt(r["id"], self.user["id"], reason,
                              r["total"], "full", items):
            QMessageBox.critical(self, "Failed", "Could not process refund.")
            return
        self._post_action(
            f"Full refund of ${r['total']:.2f} for {r['receipt_number']}.", AMBER)
        rec    = get_receipt_by_id(r["id"])
        refund = (get_refunds_for_receipt(r["id"]) or [{}])[0]
        self._maybe_restock(rec)
        print_refund(rec, refund, self.user, self)

    def _do_partial_refund(self, reason: str):
        r = self._receipt
        selected = [
            {"product_id": it["product_id"], "product_name": it["product_name"],
             "qty": it["qty"], "unit_price": it["unit_price"]}
            for it in self._item_chks if it["chk"].isChecked()
        ]
        if not selected:
            self.auth_err.setText("Select at least one item.")
            return
        amount = sum(it["qty"] * it["unit_price"] for it in selected)
        if not refund_receipt(r["id"], self.user["id"], reason,
                              amount, "partial", selected):
            QMessageBox.critical(self, "Failed", "Could not process refund.")
            return
        self._post_action(
            f"Partial refund of ${amount:.2f} for {r['receipt_number']}.", AMBER)
        rec    = get_receipt_by_id(r["id"])
        refund = (get_refunds_for_receipt(r["id"]) or [{}])[0]
        print_refund(rec, refund, self.user, self)

    def _do_exchange(self, reason: str):
        r = self._receipt
        ex_for = self.exchange_for_inp.text().strip()
        selected = [
            {"product_id": it["product_id"], "product_name": it["product_name"],
             "qty": it["qty"], "unit_price": it["unit_price"],
             "exchange_for_name": ex_for}
            for it in self._item_chks if it["chk"].isChecked()
        ]
        if not selected:
            self.auth_err.setText("Select at least one item.")
            return
        if not exchange_receipt(r["id"], self.user["id"], reason, "", selected):
            QMessageBox.critical(self, "Failed", "Could not record exchange.")
            return
        self._post_action(
            f"Exchange recorded for {r['receipt_number']}.", DARK_CARD)

    def _post_action(self, msg: str, color: str):
        self.status_lbl.setText(f"✓  {msg}")
        self.status_lbl.setStyleSheet(
            f"color:{color};font-size:12px;font-weight:700;"
            f"background:{AMBER_LIGHTEST if color==AMBER else GREEN_LIGHT if color==GREEN else '#FFF0F0' if color==RED else WARM_WHITE};"
            f"border:1px solid {color};border-radius:6px;padding:8px 12px;"
        )
        self.status_lbl.setVisible(True)
        self._reset_action_panel()
        self._load_list()
        # Re-select the same receipt to refresh highlights
        if self._receipt:
            self._reselect(self._receipt["id"])

    def _reselect(self, receipt_id: int):
        for row in range(self.list_tbl.rowCount()):
            item = self.list_tbl.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == receipt_id:
                self.list_tbl.selectRow(row)
                break

    def _maybe_restock(self, receipt: dict):
        from core.db_config import get_bool
        if not get_bool("stock_tracking", False):
            return
        from core.db_products import increment_stock
        for item in (receipt or {}).get("items", []):
            if item.get("product_id"):
                increment_stock(item["product_id"], item["quantity"])
