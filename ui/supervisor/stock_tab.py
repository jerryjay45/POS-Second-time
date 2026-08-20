"""
ui/supervisor/stock_tab.py
Stock management tab.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QComboBox, QLabel, QFrame, QHeaderView,
    QSpinBox, QAbstractItemView, QSplitter, QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_BG, AMBER_LIGHTEST,
    DARK_CARD, WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT, RED, GREEN, BLUE,
)
from core.db_products import (
    get_products, count_products, adjust_stock,
    get_all_stock_adjustments, get_low_stock_products,
    get_stock_adjustments, get_product_by_id,
    get_case_groups, get_case_group_by_id,
    adjust_case_group_stock, get_low_stock_case_groups,
)
from core.db_config import get_int
from core.db_users import get_user_by_id


def _stock_color(stock: int, threshold: int) -> str:
    if stock == 0:         return RED
    if stock <= threshold: return AMBER_DARK
    return GREEN


# ── History Dialog ────────────────────────────────────────────────────────────

class HistoryDialog(QDialog):
    def __init__(self, product_id: int, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Adjustment History — {product_name}")
        self.setMinimumSize(700, 480)
        self.setStyleSheet(f"QDialog{{background:{WARM_WHITE};}}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)

        # Header
        title = QLabel(f"📋  History for {product_name}")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:14px;font-weight:700;")
        lay.addWidget(title)

        # Table
        table = QTableWidget(); table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Change", "Reason", "By", "When", "Notes"])
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setStyleSheet(self._table_style())

        rows = get_stock_adjustments(product_id, limit=200)
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        for i, adj in enumerate(rows):
            table.insertRow(i); table.setRowHeight(i, 36)
            qty   = adj["qty_change"]
            sign  = "＋" if qty > 0 else "−"
            color = GREEN if qty > 0 else RED
            qi = QTableWidgetItem(f"{sign}{abs(qty)}")
            qi.setForeground(QColor(color)); qi.setTextAlignment(C)
            f = QFont(); f.setBold(True); qi.setFont(f)
            table.setItem(i, 0, qi)
            table.setItem(i, 1, QTableWidgetItem(adj.get("reason", "—")))
            user = get_user_by_id(adj["adjusted_by"]) if adj.get("adjusted_by") else None
            table.setItem(i, 2, QTableWidgetItem(user["full_name"] if user else "System"))
            table.setItem(i, 3, QTableWidgetItem(str(adj.get("adjusted_at", ""))[:16]))
            table.setItem(i, 4, QTableWidgetItem(""))

        if not rows:
            table.insertRow(0); table.setRowHeight(0, 48)
            lbl = QTableWidgetItem("No adjustments recorded yet.")
            lbl.setForeground(QColor(MUTED)); lbl.setTextAlignment(C)
            table.setItem(0, 0, lbl)
            table.setSpan(0, 0, 1, 5)

        lay.addWidget(table, stretch=1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _table_style(self) -> str:
        return (
            f"QTableWidget{{background:{WHITE};border:1px solid {BORDER};"
            f"border-radius:8px;font-size:13px;font-weight:500;}}"
            f"QTableWidget::item{{padding:8px 12px;"
            f"border-bottom:1px solid {BORDER_LIGHT};color:{DARK_CARD};}}"
            f"QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}"
            f"QHeaderView::section{{background:{DARK_CARD};color:{AMBER};"
            f"font-size:12px;font-weight:700;padding:8px 12px;border:none;"
            f"border-right:1px solid #333;}}"
        )


# ── Stock Tab ─────────────────────────────────────────────────────────────────

class StockTab(QWidget):

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user                   = user
        self._threshold             = get_int("low_stock_threshold", 5)
        self._selected_product_id   = None
        self._selected_product_name = ""
        self._pg_page               = 0
        self._pg_per_page           = 50
        self._pg_search             = ""
        self._build_ui()
        self._refresh_all()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8); root.setSpacing(8)

        # ── Alert bar ─────────────────────────────────────────────────
        self.alert_frame = QFrame()
        self.alert_frame.setStyleSheet(
            f"QFrame{{background:{AMBER_BG};border:1.5px solid {AMBER};border-radius:8px;}}"
        )
        af = QHBoxLayout(self.alert_frame)
        af.setContentsMargins(12, 6, 12, 6); af.setSpacing(8)
        alert_icon = QLabel("⚠")
        alert_icon.setStyleSheet(f"color:{AMBER_DARK};font-size:14px;font-weight:700;background:transparent;")
        self.alert_lbl = QLabel("")
        self.alert_lbl.setStyleSheet(f"color:{AMBER_DARK};font-size:12px;font-weight:600;background:transparent;")
        self.alert_lbl.setWordWrap(True)
        dismiss_btn = QPushButton("Dismiss"); dismiss_btn.setFixedHeight(26)
        dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER_DARK};"
            f"border:1px solid {AMBER};border-radius:5px;font-size:11px;"
            f"font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:{AMBER};color:white;}}"
        )
        dismiss_btn.clicked.connect(lambda: self.alert_frame.setVisible(False))
        af.addWidget(alert_icon); af.addWidget(self.alert_lbl, stretch=1); af.addWidget(dismiss_btn)
        self.alert_frame.setVisible(False)
        root.addWidget(self.alert_frame)

        # ── Splitter ──────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};width:1px;}}")

        # ── Left: stock list ──────────────────────────────────────────
        left = QFrame()
        left.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        ll = QVBoxLayout(left); ll.setContentsMargins(10, 10, 10, 10); ll.setSpacing(8)

        # Toolbar
        tb = QHBoxLayout(); tb.setSpacing(6)
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("🔍  Search by product name or group…")
        self.search_inp.setFixedHeight(34)
        self.search_inp.setStyleSheet(
            f"QLineEdit{{background:{WHITE};border:2px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:13px;color:{DARK_CARD};}}"
            f"QLineEdit:focus{{border-color:{AMBER};}}"
        )
        self.search_inp.returnPressed.connect(self._search)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All Stock", "Low Stock", "Out of Stock"])
        self.filter_combo.setFixedHeight(34); self.filter_combo.setFixedWidth(130)
        self.filter_combo.setStyleSheet(
            f"QComboBox{{background:{WHITE};border:2px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;color:{DARK_CARD};}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
        )
        self.filter_combo.currentIndexChanged.connect(self._search)
        refresh_btn = self._outline_btn("↻  Refresh"); refresh_btn.clicked.connect(self._refresh_all)
        tb.addWidget(self.search_inp, stretch=1); tb.addWidget(self.filter_combo); tb.addWidget(refresh_btn)
        ll.addLayout(tb)

        # Stock table — 4 cols: Product, Group, Stock, Actions
        self.stock_table = QTableWidget(); self.stock_table.setColumnCount(4)
        self.stock_table.setHorizontalHeaderLabels(["Product", "Group", "Stock", "Actions"])
        hh = self.stock_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.stock_table.setColumnWidth(2, 70)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.stock_table.setColumnWidth(3, 150)
        self.stock_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stock_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stock_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.stock_table.verticalHeader().setVisible(False)
        self.stock_table.setShowGrid(False)
        self.stock_table.setStyleSheet(self._table_style())
        ll.addWidget(self.stock_table, stretch=1)

        # Pagination
        pg_row = QHBoxLayout(); pg_row.setSpacing(8)
        self._pg_prev = self._outline_btn("← Prev"); self._pg_prev.setFixedWidth(80)
        self._pg_prev.clicked.connect(self._prev_page)
        self._pg_label = QLabel("Page 1 of 1")
        self._pg_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        self._pg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pg_next = self._outline_btn("Next →"); self._pg_next.setFixedWidth(80)
        self._pg_next.clicked.connect(self._next_page)
        pg_row.addStretch()
        pg_row.addWidget(self._pg_prev); pg_row.addWidget(self._pg_label); pg_row.addWidget(self._pg_next)
        pg_row.addStretch()
        ll.addLayout(pg_row)

        # ── Right: adjustment panel ───────────────────────────────────
        right = QFrame()
        right.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        rl = QVBoxLayout(right); rl.setContentsMargins(16, 16, 16, 16); rl.setSpacing(10)

        # Title
        self.adj_title = QLabel("Select a product to adjust")
        self.adj_title.setStyleSheet(f"color:{DARK_CARD};font-size:14px;font-weight:700;")
        self.adj_title.setWordWrap(True)
        rl.addWidget(self.adj_title)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
        rl.addWidget(sep)

        # Current stock display
        self.adj_stock_lbl = QLabel("")
        self.adj_stock_lbl.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:500;")
        rl.addWidget(self.adj_stock_lbl)

        # Quantity
        rl.addWidget(self._section_lbl("Quantity"))
        self.adj_qty = QSpinBox()
        self.adj_qty.setMinimum(1); self.adj_qty.setMaximum(99999); self.adj_qty.setValue(1)
        self.adj_qty.setFixedHeight(36)
        self.adj_qty.setStyleSheet(
            f"QSpinBox{{background:{WHITE};border:2px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:13px;color:{DARK_CARD};}}"
            f"QSpinBox:focus{{border-color:{AMBER};}}"
        )
        rl.addWidget(self.adj_qty)

        # Reason
        rl.addWidget(self._section_lbl("Reason"))
        self.adj_reason = QComboBox()
        self.adj_reason.addItems(["Restock", "Damaged", "Correction", "Return", "Other"])
        self.adj_reason.setFixedHeight(36)
        self.adj_reason.setStyleSheet(
            f"QComboBox{{background:{WHITE};border:2px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:13px;color:{DARK_CARD};}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
        )
        rl.addWidget(self.adj_reason)

        # Add / Remove / Cancel buttons
        rl.addWidget(self._section_lbl("Action"))
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.adj_add_btn = QPushButton("＋  Add Stock"); self.adj_add_btn.setFixedHeight(36)
        self.adj_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adj_add_btn.setEnabled(False)
        self.adj_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};"
            f"border:1.5px solid {GREEN};border-radius:7px;"
            f"font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}"
        )
        self.adj_add_btn.clicked.connect(self._do_add)

        self.adj_rem_btn = QPushButton("−  Remove Stock"); self.adj_rem_btn.setFixedHeight(36)
        self.adj_rem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adj_rem_btn.setEnabled(False)
        self.adj_rem_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};"
            f"border:1.5px solid {RED};border-radius:7px;"
            f"font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}"
        )
        self.adj_rem_btn.clicked.connect(self._do_remove)

        self.adj_cancel_btn = QPushButton("Cancel"); self.adj_cancel_btn.setFixedHeight(36)
        self.adj_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adj_cancel_btn.setEnabled(False)
        self.adj_cancel_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{MUTED};"
            f"border:1.5px solid {BORDER};border-radius:7px;"
            f"font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{BORDER};color:{DARK_CARD};}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}"
        )
        self.adj_cancel_btn.clicked.connect(self._cancel_adjust)
        btn_row.addWidget(self.adj_add_btn, stretch=1)
        btn_row.addWidget(self.adj_rem_btn, stretch=1)
        btn_row.addWidget(self.adj_cancel_btn)
        rl.addLayout(btn_row)

        # Feedback label
        self.adj_feedback = QLabel("")
        self.adj_feedback.setStyleSheet(f"color:{GREEN};font-size:12px;font-weight:600;")
        self.adj_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.adj_feedback)

        rl.addStretch()

        # History button at bottom
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
        rl.addWidget(sep2)
        self.hist_btn = self._outline_btn("📋  View Adjustment History")
        self.hist_btn.setEnabled(False)
        self.hist_btn.clicked.connect(self._show_history)
        rl.addWidget(self.hist_btn)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

        # ── Case Pool section — hidden when no case groups exist ──────
        self.pool_section = QFrame()
        self.pool_section.setStyleSheet(
            f"QFrame{{background:{WHITE};border:1px solid {BORDER};border-radius:10px;}}"
        )
        pl = QVBoxLayout(self.pool_section)
        pl.setContentsMargins(12, 10, 12, 10); pl.setSpacing(8)

        pool_hdr = QHBoxLayout()
        pool_title = QLabel("📦  Case Pool Stock")
        pool_title.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;background:transparent;")
        pool_hdr.addWidget(pool_title)
        pool_hdr.addStretch()
        self.pool_refresh_btn = QPushButton("↻  Refresh")
        self.pool_refresh_btn.setFixedHeight(26)
        self.pool_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pool_refresh_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER};border:1px solid {AMBER};"
            f"border-radius:5px;font-size:11px;font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:{AMBER};color:white;}}"
        )
        self.pool_refresh_btn.clicked.connect(self._load_pool_table)
        pool_hdr.addWidget(self.pool_refresh_btn)
        pl.addLayout(pool_hdr)

        self.pool_table = QTableWidget(); self.pool_table.setColumnCount(5)
        self.pool_table.setHorizontalHeaderLabels(
            ["Group Name", "Case Qty", "Pool Stock", "Add Cases", "Remove Cases"]
        )
        ph = self.pool_table.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        ph.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.pool_table.setColumnWidth(3, 140)
        self.pool_table.setColumnWidth(4, 140)
        self.pool_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pool_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.pool_table.verticalHeader().setVisible(False)
        self.pool_table.setShowGrid(False)
        self.pool_table.setMaximumHeight(200)
        self.pool_table.setStyleSheet(self._table_style())
        pl.addWidget(self.pool_table)

        self.pool_section.setVisible(False)
        root.addWidget(self.pool_section)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _refresh_all(self):
        self._threshold = get_int("low_stock_threshold", 5)
        self._load_stock_table()
        self._load_pool_table()
        self._refresh_alert()

    def _refresh_alert(self):
        low = get_low_stock_products(self._threshold)
        low_pool = get_low_stock_case_groups(self._threshold)
        if not low and not low_pool:
            self.alert_frame.setVisible(False); return
        out  = [p for p in low if p["stock"] == 0]
        warn = [p for p in low if 0 < p["stock"] <= self._threshold]
        parts = []
        if out:       parts.append(f"{len(out)} out of stock")
        if warn:      parts.append(f"{len(warn)} low (≤{self._threshold})")
        if low_pool:  parts.append(f"{len(low_pool)} case pool{'s' if len(low_pool) != 1 else ''} low")
        names = ", ".join(p["name"] for p in low[:4])
        if low_pool:
            names += (", " if names else "") + ", ".join(g["name"] for g in low_pool[:2])
        if len(low) + len(low_pool) > 5: names += f"  +{len(low)+len(low_pool)-5} more"
        self.alert_lbl.setText(f"{' · '.join(parts)}:  {names}")
        self.alert_frame.setVisible(True)

    def _load_pool_table(self):
        """Populate the Case Pool section. Hide section if no case groups exist."""
        groups = get_case_groups()
        if not groups:
            self.pool_section.setVisible(False)
            return
        self.pool_section.setVisible(True)
        self.pool_table.setRowCount(0)
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter

        for row, g in enumerate(groups):
            self.pool_table.insertRow(row)
            self.pool_table.setRowHeight(row, 40)

            name_item = QTableWidgetItem(g["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, g["id"])
            self.pool_table.setItem(row, 0, name_item)

            qty_item = QTableWidgetItem(str(g.get("case_qty") or "—"))
            qty_item.setTextAlignment(C)
            self.pool_table.setItem(row, 1, qty_item)

            pool  = g.get("pool_stock", 0)
            color = RED if pool == 0 else (AMBER_DARK if pool <= self._threshold else GREEN)
            label = "Out" if pool == 0 else (f"{pool} ⚠" if pool <= self._threshold else str(pool))
            si = QTableWidgetItem(label)
            si.setForeground(QColor(color)); si.setTextAlignment(C)
            f = QFont(); f.setBold(True); si.setFont(f)
            self.pool_table.setItem(row, 2, si)

            # Add Cases widget
            add_w = QWidget(); add_l = QHBoxLayout(add_w)
            add_l.setContentsMargins(4, 2, 4, 2); add_l.setSpacing(4)
            add_spin = QSpinBox(); add_spin.setMinimum(1); add_spin.setMaximum(9999)
            add_spin.setValue(1); add_spin.setFixedHeight(28)
            add_spin.setStyleSheet(
                f"QSpinBox{{background:{WHITE};border:1px solid {BORDER};"
                f"border-radius:5px;padding:0 4px;font-size:11px;color:{DARK_CARD};}}"
            )
            add_btn = QPushButton("＋ Add")
            add_btn.setFixedHeight(28)
            add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            add_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{GREEN};"
                f"border:1px solid {GREEN};border-radius:5px;"
                f"font-size:11px;font-weight:700;padding:0 6px;}}"
                f"QPushButton:hover{{background:{GREEN};color:white;}}"
            )
            gid = g["id"]
            uid = self.user["id"]
            add_btn.clicked.connect(
                lambda _, gid=gid, sp=add_spin: self._pool_adjust(gid, sp.value(), uid)
            )
            add_l.addWidget(add_spin); add_l.addWidget(add_btn)
            self.pool_table.setCellWidget(row, 3, add_w)

            # Remove Cases widget
            rem_w = QWidget(); rem_l = QHBoxLayout(rem_w)
            rem_l.setContentsMargins(4, 2, 4, 2); rem_l.setSpacing(4)
            rem_spin = QSpinBox(); rem_spin.setMinimum(1); rem_spin.setMaximum(9999)
            rem_spin.setValue(1); rem_spin.setFixedHeight(28)
            rem_spin.setStyleSheet(
                f"QSpinBox{{background:{WHITE};border:1px solid {BORDER};"
                f"border-radius:5px;padding:0 4px;font-size:11px;color:{DARK_CARD};}}"
            )
            rem_btn = QPushButton("− Remove")
            rem_btn.setFixedHeight(28)
            rem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rem_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{RED};"
                f"border:1px solid {RED};border-radius:5px;"
                f"font-size:11px;font-weight:700;padding:0 6px;}}"
                f"QPushButton:hover{{background:{RED};color:white;}}"
            )
            rem_btn.clicked.connect(
                lambda _, gid=gid, sp=rem_spin: self._pool_adjust(gid, -sp.value(), uid)
            )
            rem_l.addWidget(rem_spin); rem_l.addWidget(rem_btn)
            self.pool_table.setCellWidget(row, 4, rem_w)

    def _pool_adjust(self, group_id: int, delta: int, user_id: int):
        reason = "Restock" if delta > 0 else "Correction"
        adjust_case_group_stock(group_id, delta, reason, user_id)
        self._load_pool_table()
        self._refresh_alert()

    def _search(self):
        self._pg_page   = 0
        self._pg_search = self.search_inp.text().strip()
        self._load_stock_table()

    def _load_stock_table(self):
        search = self._pg_search
        flt    = self.filter_combo.currentIndex()

        if flt == 2:
            products = [p for p in get_low_stock_products(0) if p["stock"] == 0]
            if search: products = [p for p in products if search.lower() in p["name"].lower()]
            total = len(products); pages = 1
        elif flt == 1:
            products = get_low_stock_products(self._threshold)
            if search: products = [p for p in products if search.lower() in p["name"].lower()]
            total = len(products); pages = 1
        else:
            total    = count_products(search=search, exclude_cases=True)
            pages    = max(1, (total + self._pg_per_page - 1) // self._pg_per_page)
            self._pg_page = min(self._pg_page, pages - 1)
            products = get_products(search=search, exclude_cases=True,
                                    limit=self._pg_per_page,
                                    offset=self._pg_page * self._pg_per_page)

        self.stock_table.setRowCount(0)
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter

        for row, p in enumerate(products):
            self.stock_table.insertRow(row)
            self.stock_table.setRowHeight(row, 38)

            name_item = QTableWidgetItem(p["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.stock_table.setItem(row, 0, name_item)

            grp = QTableWidgetItem(p.get("group_name") or "—")
            grp.setForeground(QColor(MUTED)); grp.setTextAlignment(C)
            self.stock_table.setItem(row, 1, grp)

            stock = p.get("stock", 0)
            color = _stock_color(stock, self._threshold)
            label = "Out" if stock == 0 else (f"{stock} ⚠" if stock <= self._threshold else str(stock))
            si = QTableWidgetItem(label)
            si.setForeground(QColor(color)); si.setTextAlignment(C)
            f = QFont(); f.setBold(True); si.setFont(f)
            self.stock_table.setItem(row, 2, si)

            # Action buttons — Adjust + History
            act = QWidget(); al = QHBoxLayout(act)
            al.setContentsMargins(4, 2, 4, 2); al.setSpacing(4)
            for label, color, cb in [
                ("Adjust",  AMBER, lambda _, pid=p["id"], pname=p["name"]: self._select_product(pid, pname)),
                ("History", BLUE,  lambda _, pid=p["id"], pname=p["name"]: self._open_history(pid, pname)),
            ]:
                b = QPushButton(label); b.setFixedHeight(26)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{color};"
                    f"border:1px solid {color};border-radius:5px;"
                    f"font-size:11px;font-weight:600;padding:0 8px;}}"
                    f"QPushButton:hover{{background:{color};color:white;}}"
                )
                b.clicked.connect(cb); al.addWidget(b)
            al.addStretch()
            self.stock_table.setCellWidget(row, 3, act)

        self._pg_label.setText(f"Page {self._pg_page+1} of {pages}  ({total})")
        self._pg_prev.setEnabled(self._pg_page > 0 and flt == 0)
        self._pg_next.setEnabled(self._pg_page < pages - 1 and flt == 0)

    def _select_product(self, product_id: int, product_name: str):
        """Load product into the right panel for adjustment."""
        self._selected_product_id   = product_id
        self._selected_product_name = product_name
        p = get_product_by_id(product_id)
        stock = p["stock"] if p else 0
        color = _stock_color(stock, self._threshold)
        self.adj_title.setText(product_name)
        self.adj_stock_lbl.setText(
            f"Current stock: <span style='color:{color};font-weight:700;'>{stock} units</span>"
        )
        self.adj_stock_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.adj_qty.setValue(1)
        self.adj_reason.setCurrentIndex(0)
        self.adj_feedback.setText("")
        self.adj_add_btn.setEnabled(True)
        self.adj_rem_btn.setEnabled(True)
        self.adj_cancel_btn.setEnabled(True)
        self.hist_btn.setEnabled(True)

    def _cancel_adjust(self):
        """Deselect product and reset the right panel."""
        self._selected_product_id   = None
        self._selected_product_name = ""
        self.stock_table.clearSelection()
        self.adj_title.setText("Select a product to adjust")
        self.adj_stock_lbl.setText("")
        self.adj_qty.setValue(1)
        self.adj_reason.setCurrentIndex(0)
        self.adj_feedback.setText("")
        self.adj_add_btn.setEnabled(False)
        self.adj_rem_btn.setEnabled(False)
        self.adj_cancel_btn.setEnabled(False)
        self.hist_btn.setEnabled(False)

    def _do_add(self):
        if not self._selected_product_id: return
        qty    = self.adj_qty.value()
        reason = self.adj_reason.currentText()
        adjust_stock(self._selected_product_id, qty, reason, self.user["id"])
        self._select_product(self._selected_product_id, self._selected_product_name)
        self._load_stock_table(); self._refresh_alert()
        self.adj_feedback.setStyleSheet(f"color:{GREEN};font-size:12px;font-weight:600;")
        self.adj_feedback.setText(f"✓  Added {qty} unit{'s' if qty != 1 else ''}")

    def _do_remove(self):
        if not self._selected_product_id: return
        qty    = self.adj_qty.value()
        reason = self.adj_reason.currentText()
        adjust_stock(self._selected_product_id, -qty, reason, self.user["id"])
        self._select_product(self._selected_product_id, self._selected_product_name)
        self._load_stock_table(); self._refresh_alert()
        self.adj_feedback.setStyleSheet(f"color:{AMBER_DARK};font-size:12px;font-weight:600;")
        self.adj_feedback.setText(f"✓  Removed {qty} unit{'s' if qty != 1 else ''}")

    def _show_history(self):
        if not self._selected_product_id: return
        dlg = HistoryDialog(self._selected_product_id, self._selected_product_name, self)
        dlg.exec()

    def _open_history(self, product_id: int, product_name: str):
        """Open history dialog directly from the table action button."""
        dlg = HistoryDialog(product_id, product_name, self)
        dlg.exec()

    def _prev_page(self):
        if self._pg_page > 0:
            self._pg_page -= 1; self._load_stock_table()

    def _next_page(self):
        self._pg_page += 1; self._load_stock_table()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _outline_btn(self, text: str) -> QPushButton:
        b = QPushButton(text); b.setFixedHeight(34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{LABEL_TEXT};"
            f"border:1.5px solid {BORDER};border-radius:7px;font-size:12px;"
            f"font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}"
        )
        return b

    def _section_lbl(self, text: str) -> QLabel:
        l = QLabel(text.upper())
        l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
        return l

    def _table_style(self) -> str:
        return (
            f"QTableWidget{{background:{WHITE};border:none;"
            f"font-size:13px;font-weight:500;}}"
            f"QTableWidget::item{{padding:8px 12px;"
            f"border-bottom:1px solid {BORDER_LIGHT};color:{DARK_CARD};}}"
            f"QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}"
            f"QHeaderView::section{{background:{DARK_CARD};color:{AMBER};"
            f"font-size:12px;font-weight:700;padding:8px 12px;border:none;"
            f"border-right:1px solid #333;}}"
        )
