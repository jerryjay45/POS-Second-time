"""
ui/supervisor/supervisor_window.py
Supervisor dashboard — Products, Reports, Transactions, Void/Refund, Quick Keys.
Adapted from prototype layout and functions with amber/dark theme.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QCheckBox, QAbstractItemView,
    QMessageBox, QSplitter, QSpinBox, QDialog, QRadioButton,
)
from PyQt6.QtCore  import Qt, QTimer, QDateTime, pyqtSignal
from PyQt6.QtGui   import QColor

from ui.base_window  import BaseWindow
from utils.currency  import format_currency
from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_4, DARK_CARD,
    WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN, GREEN_LIGHT, BLUE,
)
from core.db_products import (
    get_products, get_product_by_id, delete_product,
    count_products, recalculate_all_cases,
)
from core.db_users    import get_users, get_sessions, open_session, close_session, get_user_by_id, has_open_session
from core.db_checkout import (
    get_receipts, get_receipt_by_id, void_receipt, refund_receipt,
    session_totals, count_receipts,
)
from core.db_config   import get_quick_keys, save_quick_keys, gct_rate


class SupervisorWindow(BaseWindow):
    logout_requested = pyqtSignal()

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user = user
        self._editing_product_id = None
        self.setWindowTitle("POS System — Supervisor")
        self.setMinimumSize(1280, 720)
        self._build_ui()
        self._start_clock()

    # ================================================================
    # UI BUILD
    # ================================================================

    def _build_ui(self):
        root = QWidget(); root.setStyleSheet(f"background:{WARM_WHITE};")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_tabs(), stretch=1)

    def _build_topbar(self):
        bar = QFrame(); bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{DARK};border-bottom:1px solid {DARK_4};")
        lay = QHBoxLayout(bar); lay.setContentsMargins(16, 0, 16, 0)
        left = QLabel(f"POS System  |  Supervisor:  {self.user['full_name']}")
        left.setStyleSheet("color:white;font-size:13px;font-weight:600;")
        self._clock = QLabel()
        self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clock.setStyleSheet(f"color:{MUTED};font-size:11px;font-family:'DM Mono',monospace;")
        logout = QPushButton("Logout  ↗"); logout.setFixedHeight(30)
        logout.setCursor(Qt.CursorShape.PointingHandCursor)
        logout.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:white;border:none;
            border-radius:15px;font-size:11px;font-weight:700;padding:0 16px;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        logout.clicked.connect(self._handle_logout)
        lay.addWidget(left); lay.addStretch()
        lay.addWidget(self._clock); lay.addStretch()
        lay.addWidget(logout)
        return bar

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane{{background:{WARM_WHITE};border:none;}}
            QTabBar::tab{{background:{WHITE};color:{LABEL_TEXT};border:none;
            border-bottom:2px solid transparent;padding:10px 18px;
            font-size:12px;font-weight:500;margin-right:2px;}}
            QTabBar::tab:selected{{color:{DARK_CARD};border-bottom:2px solid {AMBER};font-weight:700;}}
            QTabBar::tab:hover{{color:{DARK_CARD};}}
        """)
        self.tabs.addTab(self._build_products_tab(),     "📦  Products")
        self.tabs.addTab(self._build_reports_tab(),      "📊  Reports")
        self.tabs.addTab(self._build_transactions_tab(), "🧾  Transactions")
        # The old standalone void_refund_tab.py file was retired — its
        # functionality is superseded by the inline void/refund section
        # built into this window's own tab (see _vr_* methods below),
        # which already implements the fixed reconciliation logic.
        # NOTE: _build_void_tab() existed in the original codebase but was
        # never actually added here — only reachable via the (now deleted)
        # standalone file, and only from the Manager window. Supervisors
        # had no void/refund access at all. Adding it here fixes that.
        self.tabs.addTab(self._build_void_tab(),         "↩  Void / Refund")
        self.tabs.addTab(self._build_stock_tab(),        "📊  Stock")
        self.tabs.addTab(self._build_price_tag_tab(),    "🏷  Price Tags")
        self.tabs.addTab(self._build_quickkeys_tab(),    "⌨  Quick Keys")
        self.tabs.setCurrentIndex(0)
        return self.tabs

    # ================================================================
    # PRODUCTS TAB
    # ================================================================

    def _build_products_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(10)
        lay.addWidget(self._build_product_list(), stretch=1)
        return w

    def _build_product_list(self):
        panel = QFrame()
        panel.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(8)

        tb = QHBoxLayout(); tb.setSpacing(6)
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("🔍  Search by name, barcode, alias or group…")
        self.product_search.setFixedHeight(36)
        self.product_search.setStyleSheet(self._input_style())
        self.product_search.returnPressed.connect(self._search_products)

        clr_btn = self._product_icon_btn("clear", "Clear search")
        clr_btn.clicked.connect(lambda: (
            self.product_search.clear(),
            self.product_search.setFocus(),
            setattr(self, '_pg_page', 0),
            self._load_products(""),
        ))

        refresh_btn = self._outline_btn("↻  Refresh")
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(lambda: (setattr(self, '_pg_page', 0), self._load_products(self.product_search.text())))

        recalc_btn = self._outline_btn("⟳ Recalc Cases")
        recalc_btn.setFixedHeight(36)
        recalc_btn.setToolTip("Recalculate all case product prices from their linked single products")
        recalc_btn.clicked.connect(self._recalculate_cases)

        add_btn = QPushButton("＋  Add Product"); add_btn.setFixedHeight(36)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(self._accent_btn())
        add_btn.clicked.connect(self._open_add_product)

        tb.addWidget(self.product_search, stretch=1)
        tb.addWidget(clr_btn)
        tb.addSpacing(4)
        tb.addWidget(refresh_btn)
        tb.addWidget(recalc_btn)
        tb.addSpacing(4)
        tb.addWidget(add_btn)
        lay.addLayout(tb)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(6)
        self.product_table.setHorizontalHeaderLabels(
            ["Name", "Barcode", "Cost", "Price", "Tags", "Actions"])
        hh = self.product_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.product_table.setColumnWidth(2, 100)  # was 80 — clips JMD-scale amounts like $1,258.00
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.product_table.setColumnWidth(3, 100)  # was 80 — same
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.product_table.setColumnWidth(4, 80)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.product_table.setColumnWidth(5, 110)
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.setShowGrid(False)
        self.product_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.product_table.setStyleSheet(self._table_style())
        self.product_table.doubleClicked.connect(self._on_product_dbl_click)
        lay.addWidget(self.product_table, stretch=1)

        # Pagination controls
        pg_row = QHBoxLayout(); pg_row.setSpacing(8)
        self._pg_prev_btn = self._outline_btn("← Prev")
        self._pg_prev_btn.setFixedWidth(80)
        self._pg_prev_btn.clicked.connect(self._prev_page)
        self._pg_label = QLabel("Page 1 of 1")
        self._pg_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        self._pg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pg_next_btn = self._outline_btn("Next →")
        self._pg_next_btn.setFixedWidth(80)
        self._pg_next_btn.clicked.connect(self._next_page)
        pg_row.addStretch()
        pg_row.addWidget(self._pg_prev_btn)
        pg_row.addWidget(self._pg_label)
        pg_row.addWidget(self._pg_next_btn)
        pg_row.addStretch()
        lay.addLayout(pg_row)

        # Pagination state
        self._pg_page     = 0
        self._pg_per_page = 50
        self._pg_search   = ""
        self._load_products()
        return panel

    # ── Products: data ────────────────────────────────────────────────

    def _load_products(self, search=""):
        from core.db_products import count_products
        self._pg_search = search
        total   = count_products(search=search)
        pages   = max(1, (total + self._pg_per_page - 1) // self._pg_per_page)
        self._pg_page = min(self._pg_page, pages - 1)

        products = get_products(
            search=search,
            limit=self._pg_per_page,
            offset=self._pg_page * self._pg_per_page
        )

        self.product_table.setRowCount(0)
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        for row, p in enumerate(products):
            self.product_table.insertRow(row)
            self.product_table.setRowHeight(row, 36)
            def cell(t, color=DARK_CARD, align=None):
                c = QTableWidgetItem(str(t)); c.setForeground(QColor(color))
                if align: c.setTextAlignment(align)
                return c
            # AMBER_DARK (#BA7517) is only 3.72:1 against white — under the
            # 4.5:1 WCAG AA minimum for 12px text. This darker shade holds
            # the same amber hue at ~5.4:1, for small amber text/borders only.
            READABLE_AMBER = "#955E12"
            tags = []
            if p["gct_applicable"]: tags.append("GCT")
            if p["is_case"]:        tags.append("CASE")
            tags_str   = "  ·  ".join(tags) if tags else "—"
            tags_color = READABLE_AMBER if tags else MUTED
            self.product_table.setItem(row, 0, cell(p["name"]))
            self.product_table.setItem(row, 1, cell(p["barcode"], MUTED))
            self.product_table.setItem(row, 2, cell(f"{format_currency(p['effective_cost'])}", READABLE_AMBER, R))
            self.product_table.setItem(row, 3, cell(f"{format_currency(p['effective_selling_price'])}", GREEN, R))
            self.product_table.setItem(row, 4, cell(tags_str, tags_color, C))
            act = QWidget(); al = QHBoxLayout(act)
            al.setContentsMargins(4, 2, 4, 2); al.setSpacing(4)
            edit_btn = QPushButton("Edit"); edit_btn.setFixedHeight(26)
            edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            edit_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{READABLE_AMBER};border:1px solid {READABLE_AMBER};"
                f"border-radius:5px;font-size:12px;font-weight:600;padding:0 8px;outline:none;}}"
                f"QPushButton:hover{{background:{READABLE_AMBER};color:white;}}"
                f"QPushButton:pressed{{background:#6E440D;color:white;}}"
            )
            edit_btn.clicked.connect(lambda _, pid=p["id"]: self._edit_product(pid))
            al.addWidget(edit_btn)
            del_btn = QPushButton(); del_btn.setFixedSize(28, 26)
            from PyQt6.QtCore import QSize as _QSize
            # Icon is baked to a fixed RED pixmap, so a hover fill of solid
            # RED would make the (also-red) X invisible against its own
            # background. RED_LIGHT keeps the icon legible on hover instead
            # of trying to invert a pre-rendered icon's color via QSS.
            del_btn.setIcon(self._draw_product_icon("clear", RED)); del_btn.setIconSize(_QSize(11, 11))
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setToolTip("Delete product")
            del_btn.setStyleSheet(
                f"QPushButton{{background:transparent;border:1px solid {RED};border-radius:5px;outline:none;}}"
                f"QPushButton:hover{{background:{RED_LIGHT};border-color:{RED};}}"
                f"QPushButton:pressed{{background:#F0C9C9;}}"
            )
            del_btn.clicked.connect(lambda _, pid=p["id"]: self._delete_product(pid))
            al.addWidget(del_btn)
            al.addStretch()
            self.product_table.setCellWidget(row, 5, act)

        # Update pagination controls
        self._pg_label.setText(f"Page {self._pg_page + 1} of {pages}  ({total} products)")
        self._pg_prev_btn.setEnabled(self._pg_page > 0)
        self._pg_next_btn.setEnabled(self._pg_page < pages - 1)

    def _prev_page(self):
        if self._pg_page > 0:
            self._pg_page -= 1
            self._load_products(self._pg_search)

    def _next_page(self):
        self._pg_page += 1
        self._load_products(self._pg_search)

    def _search_products(self):
        self._pg_page = 0   # reset to first page on new search
        self._load_products(self.product_search.text().strip())

    def _on_product_dbl_click(self, index):
        barcode_item = self.product_table.item(index.row(), 1)
        if not barcode_item: return
        from core.db_products import get_product_by_barcode
        p = get_product_by_barcode(barcode_item.text())
        if p: self._edit_product(p["id"])

    def _open_add_product(self):
        from ui.supervisor.product_dialog import ProductDialog
        dlg = ProductDialog(self.user, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_products(self.product_search.text())

    def _edit_product(self, pid: int):
        from ui.supervisor.product_dialog import ProductDialog
        dlg = ProductDialog(self.user, self, editing_id=pid)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load_products(self.product_search.text())

    def _delete_product(self, pid: int):
        p = get_product_by_id(pid)
        if not p: return
        reply = QMessageBox.question(self, "Delete", f"Delete '{p['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_product(pid); self._load_products(self.product_search.text())

    def _recalculate_cases(self):
        """Recalculate all case product prices from their linked single products."""
        from core.db_config import get as cfg_get
        try:
            pct = float(cfg_get("case_profit_pct", "0.10"))
        except (ValueError, TypeError):
            pct = 0.10
        n = recalculate_all_cases(pct)
        if n:
            QMessageBox.information(
                self, "Cases Recalculated",
                f"{n} case product{'s' if n != 1 else ''} repriced "
                f"at {pct*100:.1f}% markup over cost."
            )
        else:
            QMessageBox.information(
                self, "Cases Recalculated",
                "No case products found with a linked single product and cost > 0."
            )

    # ── Case toggle + mode switch ─────────────────────────────────────────────


    # ================================================================
    # REPORTS TAB
    # ================================================================

    def _build_reports_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QHBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)

        # Left: cashier list
        left = QFrame(); left.setFixedWidth(240)
        left.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        ll = QVBoxLayout(left); ll.setContentsMargins(10,10,10,10); ll.setSpacing(6)
        ll.addWidget(self._section_lbl("Cashiers"))
        self.rpt_cashier_search = QLineEdit()
        self.rpt_cashier_search.setPlaceholderText("🔍  Search cashier…")
        self.rpt_cashier_search.setFixedHeight(30)
        self.rpt_cashier_search.setStyleSheet(self._input_style())
        self.rpt_cashier_search.textChanged.connect(self._rpt_filter_cashiers)
        ll.addWidget(self.rpt_cashier_search)
        self.rpt_cashier_list = QTableWidget(); self.rpt_cashier_list.setColumnCount(1)
        self.rpt_cashier_list.setHorizontalHeaderLabels(["Name"])
        self.rpt_cashier_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rpt_cashier_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rpt_cashier_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rpt_cashier_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rpt_cashier_list.verticalHeader().setVisible(False)
        self.rpt_cashier_list.setShowGrid(False)
        self.rpt_cashier_list.setStyleSheet(self._table_style())
        self.rpt_cashier_list.selectionModel().selectionChanged.connect(self._rpt_on_cashier_selected)
        ll.addWidget(self.rpt_cashier_list, stretch=1)

        # Right panel
        right = QFrame()
        right.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        rl = QVBoxLayout(right); rl.setContentsMargins(12,12,12,12); rl.setSpacing(8)

        # Summary cards
        cards = QHBoxLayout(); cards.setSpacing(8)
        self.rpt_cards = {}
        for key, label, color in [
            ("total_sales","TOTAL SALES",AMBER),("total_gct","TOTAL GCT",AMBER_DARK),
            ("transactions","TRANSACTIONS",BLUE),("discounts","DISCOUNTS",GREEN),
        ]:
            card = QFrame()
            card.setStyleSheet(f"background:{WARM_WHITE};border-radius:8px;border:1px solid {BORDER};")
            cl = QVBoxLayout(card); cl.setContentsMargins(12,8,12,8); cl.setSpacing(2)
            t = QLabel(label); t.setStyleSheet(f"color:{LABEL_TEXT};font-size:10px;font-weight:700;")
            v = QLabel("—"); v.setStyleSheet(f"color:{color};font-size:22px;font-weight:700;")
            cl.addWidget(t); cl.addWidget(v); self.rpt_cards[key] = v; cards.addWidget(card)
        rl.addLayout(cards)

        # Single action bar row
        sb = QHBoxLayout(); sb.setSpacing(8)
        self.rpt_session_header = QLabel("Select a cashier")
        self.rpt_session_header.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;font-weight:600;")
        self.rpt_search_bar = QLineEdit()
        self.rpt_search_bar.setPlaceholderText("🔍  #0012  or  2024-06-01  or  2024-06-01 to 2024-06-30")
        self.rpt_search_bar.setFixedHeight(30); self.rpt_search_bar.setFixedWidth(300)
        self.rpt_search_bar.setStyleSheet(self._input_style())
        self.rpt_search_bar.textChanged.connect(self._rpt_filter_sessions)
        self.rpt_refresh_btn = self._outline_btn("↻  Refresh"); self.rpt_refresh_btn.clicked.connect(self._rpt_refresh)
        self.rpt_close_btn   = self._danger_btn("✕  Close"); self.rpt_close_btn.setEnabled(False); self.rpt_close_btn.clicked.connect(self._rpt_close_session)
        self.rpt_open_btn    = self._success_btn("＋  Open"); self.rpt_open_btn.setEnabled(False); self.rpt_open_btn.clicked.connect(self._rpt_open_session)
        self.rpt_print_btn   = self._outline_btn("🖨  Print"); self.rpt_print_btn.setEnabled(False); self.rpt_print_btn.clicked.connect(self._rpt_print_session)
        sb.addWidget(self.rpt_session_header); sb.addStretch()
        sb.addWidget(self.rpt_search_bar); sb.addWidget(self.rpt_refresh_btn)
        sb.addWidget(self.rpt_close_btn); sb.addWidget(self.rpt_open_btn); sb.addWidget(self.rpt_print_btn)
        rl.addLayout(sb)

        self.rpt_session_list = QTableWidget(); self.rpt_session_list.setColumnCount(5)
        self.rpt_session_list.setHorizontalHeaderLabels(["Session","Status","Opened","Closed","Sales"])
        hh = self.rpt_session_list.horizontalHeader()
        for c in range(5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.rpt_session_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rpt_session_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rpt_session_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rpt_session_list.verticalHeader().setVisible(False)
        self.rpt_session_list.setShowGrid(False)
        self.rpt_session_list.setStyleSheet(self._table_style())
        self.rpt_session_list.selectionModel().selectionChanged.connect(self._rpt_on_session_selected)
        rl.addWidget(self.rpt_session_list, stretch=1)

        lay.addWidget(left); lay.addWidget(right, stretch=1)
        self._rpt_all_cashiers=[]; self._rpt_all_sessions=[]; self._rpt_selected_cashier_id=None; self._rpt_selected_session_id=None
        self._rpt_load_cashiers()
        return w

    def _rpt_load_cashiers(self):
        from core.db_users import get_users
        self._rpt_all_cashiers = get_users()   # all roles
        self._rpt_fill_cashier_list(self._rpt_all_cashiers)

    def _rpt_fill_cashier_list(self, cashiers):
        self.rpt_cashier_list.setRowCount(0)
        for i, c in enumerate(cashiers):
            self.rpt_cashier_list.insertRow(i); self.rpt_cashier_list.setRowHeight(i, 38)
            item = QTableWidgetItem(c["full_name"]); item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setForeground(QColor(DARK_CARD)); self.rpt_cashier_list.setItem(i, 0, item)

    def _rpt_filter_cashiers(self, text):
        f = [c for c in self._rpt_all_cashiers if text.lower() in c["full_name"].lower()] if text else self._rpt_all_cashiers
        self._rpt_fill_cashier_list(f)

    def _rpt_on_cashier_selected(self):
        row = self.rpt_cashier_list.currentRow()
        if row < 0: return
        item = self.rpt_cashier_list.item(row, 0)
        if not item: return
        self._rpt_selected_cashier_id = item.data(Qt.ItemDataRole.UserRole)
        self.rpt_session_header.setText(f"Sessions — {item.text()}")
        self.rpt_open_btn.setEnabled(True)
        self._rpt_load_sessions(self._rpt_selected_cashier_id)

    def _rpt_load_sessions(self, user_id):
        sessions = get_sessions(user_id=user_id)
        # Enrich each session with live totals from receipts DB
        for s in sessions:
            st = session_totals(s["id"])
            s["_sales"] = st.get("total_sales", 0) or 0
            s["_gct"]   = st.get("total_gct", 0) or 0
            s["_txns"]  = st.get("transaction_count", 0) or 0
            s["_disc"]  = st.get("total_discount", 0) or 0
        self._rpt_all_sessions = sessions
        self._rpt_fill_session_list(sessions)
        self._rpt_clear_cards()

    def _rpt_clear_cards(self):
        for key in self.rpt_cards:
            self.rpt_cards[key].setText("—")

    def _rpt_fill_session_list(self, sessions):
        self.rpt_session_list.setRowCount(0)
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        for i, s in enumerate(sessions):
            self.rpt_session_list.insertRow(i); self.rpt_session_list.setRowHeight(i, 38)
            num = QTableWidgetItem(f"#{s['id']:04d}"); num.setData(Qt.ItemDataRole.UserRole, s["id"])
            num.setForeground(QColor(DARK_CARD))
            stat = QTableWidgetItem(s["status"].capitalize())
            stat.setForeground(QColor(GREEN if s["status"]=="open" else MUTED))
            opened = QTableWidgetItem(str(s["opened_at"])[:16])
            opened.setForeground(QColor(DARK_CARD))
            closed = QTableWidgetItem(str(s["closed_at"])[:16] if s["closed_at"] else "—")
            closed.setForeground(QColor(DARK_CARD))
            # Use live sales from enriched key, fallback to stored value
            live_sales = s.get("_sales", s.get("total_sales", 0))
            txns = s.get("_txns", 0)
            sales = QTableWidgetItem(f"{format_currency(live_sales)}  ({txns} txns)")
            sales.setForeground(QColor(AMBER)); sales.setTextAlignment(R)
            for col, it in enumerate([num, stat, opened, closed, sales]):
                self.rpt_session_list.setItem(i, col, it)

    def _rpt_filter_sessions(self, text):
        text = text.strip()
        if not text:
            self._rpt_fill_session_list(self._rpt_all_sessions)
            self._rpt_clear_cards()
            return

        # Date range: "2024-06-01 to 2024-06-30"
        if " to " in text.lower():
            parts = text.lower().split(" to ")
            date_from = parts[0].strip()
            date_to   = parts[1].strip() if len(parts) > 1 else ""
            filtered = [
                s for s in self._rpt_all_sessions
                if str(s.get("opened_at", ""))[:10] >= date_from
                and (not date_to or str(s.get("opened_at", ""))[:10] <= date_to)
            ]
        # Session number: "#0012" or "12"
        elif text.startswith("#") or text.isdigit():
            num = text.lstrip("#")
            filtered = [s for s in self._rpt_all_sessions
                        if num in f"{s['id']:04d}"]
        # Single date or partial date: "2024-06"
        else:
            filtered = [s for s in self._rpt_all_sessions
                        if text in str(s.get("opened_at", ""))]

        self._rpt_fill_session_list(filtered)
        self._rpt_clear_cards()

    def _rpt_on_session_selected(self):
        row = self.rpt_session_list.currentRow()
        if row < 0: return
        item = self.rpt_session_list.item(row, 0)
        if not item: return
        self._rpt_selected_session_id = item.data(Qt.ItemDataRole.UserRole)
        stat = self.rpt_session_list.item(row, 1)
        self.rpt_close_btn.setEnabled(bool(stat and stat.text().lower() == "open"))
        self.rpt_print_btn.setEnabled(True)
        # Update summary cards for the selected session
        session = next((s for s in self._rpt_all_sessions
                        if s["id"] == self._rpt_selected_session_id), None)
        if session:
            self.rpt_cards["total_sales"].setText(f"{format_currency(session['_sales'])}")
            self.rpt_cards["total_gct"].setText(f"{format_currency(session['_gct'])}")
            self.rpt_cards["transactions"].setText(str(session["_txns"]))
            self.rpt_cards["discounts"].setText(f"{format_currency(session['_disc'])}")

    def _rpt_refresh(self):
        if self._rpt_selected_cashier_id: self._rpt_load_sessions(self._rpt_selected_cashier_id)

    def _rpt_open_session(self):
        if not self._rpt_selected_cashier_id: return
        # Block if cashier already has an open session
        if has_open_session(self._rpt_selected_cashier_id):
            QMessageBox.warning(self, "Session Already Open",
                "This cashier already has an open session.\n"
                "Close it before opening a new one.")
            return
        session_id = open_session(self._rpt_selected_cashier_id, opened_by=self.user["id"])
        # Broadcast so waiting cashier window can activate
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if hasattr(app, "session_opened"):
            app.session_opened.emit(self._rpt_selected_cashier_id)
        self._rpt_refresh()

    def _rpt_close_session(self):
        if not self._rpt_selected_session_id: return
        reply = QMessageBox.question(self, "Close Session",
            "Close this cashier session?\n\n"
            "The cashier will be notified and logged out after their next sale.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        st = session_totals(self._rpt_selected_session_id)
        closed = close_session(self._rpt_selected_session_id,
                               st.get("total_sales", 0),
                               closed_by=self.user["id"])
        if closed:
            # Broadcast to any open cashier window via the app instance
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if hasattr(app, "session_closed"):
                app.session_closed.emit(self._rpt_selected_session_id)
        self._rpt_refresh()

    def _rpt_print_session(self):
        if not self._rpt_selected_session_id: return
        from core.db_users import get_session_by_id
        session = get_session_by_id(self._rpt_selected_session_id)
        if not session: return

        # ── Print options dialog ──────────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle("Print Session Report")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet(f"background:{WHITE};")
        dl = QVBoxLayout(dlg); dl.setContentsMargins(20, 16, 20, 16); dl.setSpacing(12)

        title = QLabel("Print Options")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:14px;font-weight:700;")
        dl.addWidget(title)

        # Report type
        type_lbl = QLabel("Report Type")
        type_lbl.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
        dl.addWidget(type_lbl)

        from PyQt6.QtWidgets import QButtonGroup
        full_rb    = QRadioButton("Full Z-Report  (all items, product totals, group totals, GCT, discounts, voids)")
        products_rb= QRadioButton("Product Summary  (qty and $ sold per product, no per-receipt detail)")
        summary_rb = QRadioButton("Summary Only  (totals, group totals, GCT, discounts, voids)")
        full_rb.setChecked(True)
        btn_group = QButtonGroup(dlg)
        btn_group.addButton(full_rb)
        btn_group.addButton(products_rb)
        btn_group.addButton(summary_rb)
        rb_style = (
            f"QRadioButton{{color:{DARK_CARD};font-size:12px;spacing:8px;}}"
            f"QRadioButton::indicator{{width:16px;height:16px;border-radius:8px;"
            f"border:2px solid {BORDER};background:white;}}"
            f"QRadioButton::indicator:checked{{border:2px solid {AMBER};"
            f"background:{AMBER};}}"
            f"QRadioButton::indicator:hover{{border:2px solid {AMBER};}}"
        )
        for rb in (full_rb, products_rb, summary_rb):
            rb.setStyleSheet(rb_style)
            rb.setMinimumWidth(480)
        dl.addWidget(full_rb)
        dl.addWidget(products_rb)
        dl.addWidget(summary_rb)

        # Copies
        copies_row = QHBoxLayout()
        copies_lbl = QLabel("Copies:")
        copies_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;")
        copies_spin = QSpinBox(); copies_spin.setMinimum(1); copies_spin.setMaximum(5)
        copies_spin.setValue(1); copies_spin.setFixedHeight(30); copies_spin.setFixedWidth(60)
        copies_spin.setStyleSheet(self._input_style())
        copies_row.addWidget(copies_lbl); copies_row.addWidget(copies_spin); copies_row.addStretch()
        dl.addLayout(copies_row)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
        dl.addWidget(div)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        cancel_btn = QPushButton("Cancel"); cancel_btn.setFixedHeight(34)
        cancel_btn.setStyleSheet(
            f"QPushButton{{background:{DARK_CARD};color:white;border:none;"
            f"border-radius:7px;font-size:12px;padding:0 14px;}}"
            f"QPushButton:hover{{background:#444;}}"
        )
        cancel_btn.clicked.connect(dlg.reject)
        print_btn = QPushButton("🖨  Print"); print_btn.setFixedHeight(34)
        print_btn.setStyleSheet(self._accent_btn())
        print_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn); btn_row.addWidget(print_btn, stretch=1)
        dl.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if full_rb.isChecked():
            report_type = "full"
        elif products_rb.isChecked():
            report_type = "products"
        else:
            report_type = "summary"
        copies      = copies_spin.value()

        from utils.print_manager import print_session
        print_session(session, report_type=report_type, copies=copies, parent=self)

    # ================================================================
    # TRANSACTIONS TAB
    # ================================================================

    def _build_transactions_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)
        sr = QHBoxLayout(); sr.setSpacing(8)
        self.tx_search = QLineEdit()
        self.tx_search.setPlaceholderText("🔍  Receipt #, cashier or date (YYYY-MM-DD)…")
        self.tx_search.setFixedHeight(32); self.tx_search.setStyleSheet(self._input_style())
        self.tx_search.returnPressed.connect(self._tx_search_fn)
        self.tx_status_filter = QComboBox()
        self.tx_status_filter.addItems(["All Statuses","Completed","Voided","Refunded"])
        self.tx_status_filter.setFixedHeight(32); self.tx_status_filter.setFixedWidth(130)
        self.tx_status_filter.setStyleSheet(self._combo_style())
        search_btn = QPushButton("Search"); search_btn.setFixedHeight(32)
        search_btn.setStyleSheet(self._accent_btn()); search_btn.clicked.connect(self._tx_search_fn)
        refresh_btn = self._outline_btn("↻  Refresh"); refresh_btn.clicked.connect(self._tx_search_fn)
        self.tx_reprint_btn = self._outline_btn("🖨  Reprint")
        self.tx_reprint_btn.setEnabled(False); self.tx_reprint_btn.clicked.connect(self._tx_reprint)
        sr.addWidget(self.tx_search, stretch=1)
        sr.addWidget(self.tx_status_filter); sr.addWidget(search_btn)
        sr.addWidget(refresh_btn); sr.addWidget(self.tx_reprint_btn)
        lay.addLayout(sr)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};width:1px;}}")
        left = QFrame(); left.setStyleSheet(f"background:{WHITE};border-radius:8px;border:1px solid {BORDER};")
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0)
        self.tx_table = QTableWidget(); self.tx_table.setColumnCount(6)
        self.tx_table.setHorizontalHeaderLabels(["Receipt #","Cashier","Date","Time","Total","Status"])
        hh = self.tx_table.horizontalHeader()
        for c in range(6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.tx_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tx_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tx_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tx_table.verticalHeader().setVisible(False); self.tx_table.setShowGrid(False)
        self.tx_table.setStyleSheet(self._table_style())
        self.tx_table.itemClicked.connect(self._tx_on_row_selected_by_item)
        ll.addWidget(self.tx_table, stretch=1)

        # Pagination controls
        tx_pg_row = QHBoxLayout(); tx_pg_row.setSpacing(8)
        self._tx_pg_prev = self._outline_btn("← Prev"); self._tx_pg_prev.setFixedWidth(80)
        self._tx_pg_prev.clicked.connect(self._tx_prev_page)
        self._tx_pg_label = QLabel("Page 1 of 1")
        self._tx_pg_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        self._tx_pg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tx_pg_next = self._outline_btn("Next →"); self._tx_pg_next.setFixedWidth(80)
        self._tx_pg_next.clicked.connect(self._tx_next_page)
        tx_pg_row.addStretch()
        tx_pg_row.addWidget(self._tx_pg_prev)
        tx_pg_row.addWidget(self._tx_pg_label)
        tx_pg_row.addWidget(self._tx_pg_next)
        tx_pg_row.addStretch()
        ll.addLayout(tx_pg_row)

        right = QFrame()
        right.setStyleSheet(f"background:{WHITE};border-radius:8px;border:1px solid {BORDER};")
        rl = QVBoxLayout(right); rl.setContentsMargins(14,14,14,14); rl.setSpacing(6)
        self.tx_detail_title = QLabel("Select a transaction")
        self.tx_detail_title.setStyleSheet(f"color:{DARK_CARD};font-size:14px;font-weight:700;")
        self.tx_detail_meta = QLabel(""); self.tx_detail_meta.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;font-weight:500;"); self.tx_detail_meta.setWordWrap(True)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setStyleSheet(f"color:{BORDER};")
        self.tx_items_table = QTableWidget(); self.tx_items_table.setColumnCount(4)
        self.tx_items_table.setHorizontalHeaderLabels(["Item","Qty","Price","Total"])
        hh2 = self.tx_items_table.horizontalHeader()
        for c in range(4): hh2.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.tx_items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tx_items_table.verticalHeader().setVisible(False); self.tx_items_table.setShowGrid(False)
        self.tx_items_table.setStyleSheet(self._table_style())
        self.tx_footer = QLabel(""); self.tx_footer.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
        self.tx_footer.setAlignment(Qt.AlignmentFlag.AlignRight); self.tx_footer.setWordWrap(True)
        rl.addWidget(self.tx_detail_title); rl.addWidget(self.tx_detail_meta)
        rl.addWidget(sep); rl.addWidget(self.tx_items_table, stretch=1); rl.addWidget(self.tx_footer)
        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 1)
        lay.addWidget(splitter, stretch=1)

        # Pagination state
        self._tx_pg_page     = 0
        self._tx_pg_per_page = 50
        self._tx_pg_search   = ""
        self._tx_pg_status   = ""
        self._tx_load(); return w

    def _tx_load(self, search="", status_filter=""):
        self._tx_pg_search = search
        self._tx_pg_status = status_filter
        sf = status_filter.lower() if status_filter and status_filter != "All Statuses" else None
        total = count_receipts(search=search, status=sf)
        pages = max(1, (total + self._tx_pg_per_page - 1) // self._tx_pg_per_page)
        self._tx_pg_page = min(self._tx_pg_page, pages - 1)
        receipts = get_receipts(
            search=search, status=sf,
            limit=self._tx_pg_per_page,
            offset=self._tx_pg_page * self._tx_pg_per_page
        )
        self.tx_table.setRowCount(0)
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        sc_map = {"completed":GREEN,"voided":RED,"refunded":AMBER_DARK}
        for i, r in enumerate(receipts):
            self.tx_table.insertRow(i); self.tx_table.setRowHeight(i, 38)
            num = QTableWidgetItem(r["receipt_number"]); num.setData(Qt.ItemDataRole.UserRole, r["id"])
            u = get_user_by_id(r["user_id"]); cname = u["full_name"] if u else f"#{r['user_id']}"
            dt = str(r["created_at"])
            self.tx_table.setItem(i, 0, num)
            self.tx_table.setItem(i, 1, QTableWidgetItem(cname))
            self.tx_table.setItem(i, 2, QTableWidgetItem(dt[:10]))
            self.tx_table.setItem(i, 3, QTableWidgetItem(dt[11:19]))
            tot = QTableWidgetItem(f"{format_currency(r['total'])}"); tot.setForeground(QColor(AMBER)); tot.setTextAlignment(R)
            self.tx_table.setItem(i, 4, tot)
            sc = sc_map.get(r["status"], MUTED)
            stat = QTableWidgetItem(r["status"].capitalize()); stat.setForeground(QColor(sc)); stat.setTextAlignment(C)
            self.tx_table.setItem(i, 5, stat)
        self._tx_pg_label.setText(f"Page {self._tx_pg_page + 1} of {pages}  ({total} transactions)")
        self._tx_pg_prev.setEnabled(self._tx_pg_page > 0)
        self._tx_pg_next.setEnabled(self._tx_pg_page < pages - 1)

    def _tx_prev_page(self):
        if self._tx_pg_page > 0:
            self._tx_pg_page -= 1
            self._tx_load(self._tx_pg_search, self._tx_pg_status)

    def _tx_next_page(self):
        self._tx_pg_page += 1
        self._tx_load(self._tx_pg_search, self._tx_pg_status)

    def _tx_search_fn(self):
        self._tx_pg_page = 0
        self._tx_load(search=self.tx_search.text().strip(), status_filter=self.tx_status_filter.currentText())

    def _tx_on_row_selected_by_item(self, clicked_item):
        """Called when user clicks any cell — route to main handler."""
        self._tx_on_row_selected()

    def _tx_on_row_selected(self):
        row = self.tx_table.currentRow(); item = self.tx_table.item(row, 0)
        if not item: return
        receipt = get_receipt_by_id(item.data(Qt.ItemDataRole.UserRole))
        if not receipt: return
        u = get_user_by_id(receipt["user_id"]); cname = u["full_name"] if u else "—"
        self.tx_detail_title.setText(f"Receipt {receipt['receipt_number']}")
        self.tx_detail_meta.setText(f"Cashier: {cname}\nDate: {str(receipt['created_at'])[:16]}\nStatus: {receipt['status'].capitalize()}")
        items = receipt.get("items", [])
        self.tx_items_table.setRowCount(len(items))
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        for r, it in enumerate(items):
            self.tx_items_table.setItem(r, 0, QTableWidgetItem(it["product_name"]))
            qi = QTableWidgetItem(str(it["quantity"])); qi.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.tx_items_table.setItem(r, 1, qi)
            pi = QTableWidgetItem(f"{format_currency(it['unit_price'])}"); pi.setTextAlignment(R); self.tx_items_table.setItem(r, 2, pi)
            ti = QTableWidgetItem(f"{format_currency(it['line_total'])}"); ti.setForeground(QColor(GREEN)); ti.setTextAlignment(R); self.tx_items_table.setItem(r, 3, ti)
        self.tx_footer.setText(f"Subtotal: {format_currency(receipt['subtotal'])}  |  GCT: {format_currency(receipt['gct_amount'])}  |  <b>Total: {format_currency(receipt['total'])}</b>")
        self.tx_footer.setTextFormat(Qt.TextFormat.RichText)
        self.tx_reprint_btn.setEnabled(True)

    def _tx_reprint(self):
        row = self.tx_table.currentRow()
        item = self.tx_table.item(row, 0)
        if not item:
            return
        receipt_number = item.text()
        from utils.print_manager import reprint_receipt
        reprint_receipt(receipt_number, parent=self)

    # ================================================================
    # VOID / REFUND TAB
    # ================================================================

    def _build_void_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)

        # ── Search bar ─────────────────────────────────────────────────
        sr = QHBoxLayout(); sr.setSpacing(8)
        self.vr_search = QLineEdit()
        self.vr_search.setPlaceholderText("🔍  Receipt #, cashier or date (YYYY-MM-DD)…")
        self.vr_search.setFixedHeight(32); self.vr_search.setStyleSheet(self._input_style())
        self.vr_search.returnPressed.connect(self._vr_search_fn)
        self.vr_status_filter = QComboBox()
        self.vr_status_filter.addItems(["Completed Only", "All Statuses"])
        self.vr_status_filter.setFixedHeight(32); self.vr_status_filter.setFixedWidth(150)
        self.vr_status_filter.setStyleSheet(self._combo_style())
        search_btn = QPushButton("Search"); search_btn.setFixedHeight(32)
        search_btn.setStyleSheet(self._accent_btn()); search_btn.clicked.connect(self._vr_search_fn)
        refresh_btn = self._outline_btn("↻  Refresh"); refresh_btn.clicked.connect(self._vr_search_fn)
        sr.addWidget(self.vr_search, stretch=1); sr.addWidget(self.vr_status_filter)
        sr.addWidget(search_btn); sr.addWidget(refresh_btn)
        lay.addLayout(sr)

        # ── Splitter: left = receipts list, right = detail + actions ──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};width:1px;}}")

        # Left — receipts table
        left = QFrame(); left.setStyleSheet(f"background:{WHITE};border-radius:8px;border:1px solid {BORDER};")
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0)
        self.vr_table = QTableWidget(); self.vr_table.setColumnCount(6)
        self.vr_table.setHorizontalHeaderLabels(["Receipt #","Cashier","Date","Time","Total","Status"])
        hh = self.vr_table.horizontalHeader()
        for c in range(6): hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.vr_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vr_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vr_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.vr_table.verticalHeader().setVisible(False); self.vr_table.setShowGrid(False)
        self.vr_table.setStyleSheet(self._table_style())
        self.vr_table.itemClicked.connect(lambda _: self._vr_on_row_selected())
        ll.addWidget(self.vr_table, stretch=1)

        # Pagination
        vr_pg_row = QHBoxLayout(); vr_pg_row.setSpacing(8)
        self._vr_pg_prev = self._outline_btn("← Prev"); self._vr_pg_prev.setFixedWidth(80)
        self._vr_pg_prev.clicked.connect(self._vr_prev_page)
        self._vr_pg_label = QLabel("Page 1 of 1")
        self._vr_pg_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        self._vr_pg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vr_pg_next = self._outline_btn("Next →"); self._vr_pg_next.setFixedWidth(80)
        self._vr_pg_next.clicked.connect(self._vr_next_page)
        vr_pg_row.addStretch()
        vr_pg_row.addWidget(self._vr_pg_prev); vr_pg_row.addWidget(self._vr_pg_label); vr_pg_row.addWidget(self._vr_pg_next)
        vr_pg_row.addStretch()
        ll.addLayout(vr_pg_row)

        # Right — detail + actions panel
        right = QFrame()
        right.setStyleSheet(f"background:{WHITE};border-radius:8px;border:1px solid {BORDER};")
        rl = QVBoxLayout(right); rl.setContentsMargins(14,14,14,14); rl.setSpacing(8)

        self.vr_receipt_title = QLabel("Select a receipt")
        self.vr_receipt_title.setStyleSheet(f"color:{DARK_CARD};font-size:14px;font-weight:700;")
        self.vr_receipt_meta  = QLabel("")
        self.vr_receipt_meta.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;font-weight:500;")
        self.vr_receipt_meta.setWordWrap(True)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")

        # Items table with checkboxes for partial refund
        self.vr_items_table = QTableWidget(); self.vr_items_table.setColumnCount(5)
        self.vr_items_table.setHorizontalHeaderLabels(["Item","Sold Qty","Refund Qty","Price","Line Refund"])
        hh2 = self.vr_items_table.horizontalHeader()
        hh2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for c in [1,2,3,4]: hh2.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.vr_items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vr_items_table.verticalHeader().setVisible(False); self.vr_items_table.setShowGrid(False)
        self.vr_items_table.setStyleSheet(self._table_style())

        self.vr_totals = QLabel("")
        self.vr_totals.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
        self.vr_totals.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Refund mode
        mode_row = QHBoxLayout(); mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("Mode:"))
        self.vr_refund_mode = QComboBox()
        self.vr_refund_mode.addItems(["Full Void / Refund", "Partial Refund"])
        self.vr_refund_mode.setFixedHeight(30); self.vr_refund_mode.setStyleSheet(self._combo_style())
        self.vr_refund_mode.currentIndexChanged.connect(self._vr_on_mode_changed)
        mode_row.addWidget(self.vr_refund_mode, stretch=1)

        # Reason input
        self.vr_reason = QLineEdit()
        self.vr_reason.setPlaceholderText("Reason (required)…")
        self.vr_reason.setFixedHeight(30); self.vr_reason.setStyleSheet(self._input_style())
        self.vr_reason.textChanged.connect(self._vr_update_buttons)

        # Selected amount label (for partial)
        self.vr_amount_lbl = QLabel("")
        self.vr_amount_lbl.setStyleSheet(f"color:{AMBER};font-size:12px;font-weight:600;")
        self.vr_amount_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Status banner
        self.vr_status_banner = QLabel("")
        self.vr_status_banner.setVisible(False)
        self.vr_status_banner.setWordWrap(True)

        # Action buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.vr_void_btn = QPushButton("↩  Void Transaction"); self.vr_void_btn.setFixedHeight(34)
        self.vr_void_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vr_void_btn.setStyleSheet(f"QPushButton{{background:{RED};color:white;border:none;border-radius:7px;font-size:12px;font-weight:700;}}QPushButton:hover{{background:#7A1E1E;}}QPushButton:disabled{{background:{MUTED};color:white;}}")
        self.vr_void_btn.setEnabled(False); self.vr_void_btn.clicked.connect(self._vr_do_void)
        self.vr_refund_btn = QPushButton("↩  Issue Refund"); self.vr_refund_btn.setFixedHeight(34)
        self.vr_refund_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vr_refund_btn.setStyleSheet(f"QPushButton{{background:{AMBER};color:white;border:none;border-radius:7px;font-size:12px;font-weight:700;}}QPushButton:hover{{background:{AMBER_DARK};}}QPushButton:disabled{{background:{MUTED};color:white;}}")
        self.vr_refund_btn.setEnabled(False); self.vr_refund_btn.clicked.connect(self._vr_do_refund)
        btn_row.addWidget(self.vr_void_btn, stretch=1); btn_row.addWidget(self.vr_refund_btn, stretch=1)

        rl.addWidget(self.vr_receipt_title)
        rl.addWidget(self.vr_receipt_meta)
        rl.addWidget(sep)
        rl.addWidget(self.vr_items_table, stretch=1)
        rl.addWidget(self.vr_totals)
        rl.addLayout(mode_row)
        rl.addWidget(self.vr_reason)
        rl.addWidget(self.vr_amount_lbl)
        rl.addWidget(self.vr_status_banner)
        rl.addLayout(btn_row)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 1)
        lay.addWidget(splitter, stretch=1)

        self._vr_selected_tx_id     = None
        self._vr_selected_tx_status = None
        self._vr_items_data         = []
        self._vr_pg_page            = 0
        self._vr_pg_per_page        = 50
        self._vr_pg_search          = ""
        self._vr_pg_status          = "completed"
        self._vr_load()
        return w

    def _vr_load(self, search="", status_filter="completed"):
        self._vr_pg_search = search
        self._vr_pg_status = status_filter
        sf = None if status_filter == "" else status_filter
        total = count_receipts(search=search, status=sf)
        pages = max(1, (total + self._vr_pg_per_page - 1) // self._vr_pg_per_page)
        self._vr_pg_page = min(self._vr_pg_page, pages - 1)
        receipts = get_receipts(
            search=search, status=sf,
            limit=self._vr_pg_per_page,
            offset=self._vr_pg_page * self._vr_pg_per_page
        )
        self.vr_table.setRowCount(0)
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        sc_map = {"completed":GREEN,"voided":RED,"refunded":AMBER_DARK}
        for i, r in enumerate(receipts):
            self.vr_table.insertRow(i); self.vr_table.setRowHeight(i, 38)
            num = QTableWidgetItem(r["receipt_number"]); num.setData(Qt.ItemDataRole.UserRole, r["id"])
            u = get_user_by_id(r["user_id"]); cname = u["full_name"] if u else "—"
            dt = str(r["created_at"])
            self.vr_table.setItem(i, 0, num); self.vr_table.setItem(i, 1, QTableWidgetItem(cname))
            self.vr_table.setItem(i, 2, QTableWidgetItem(dt[:10])); self.vr_table.setItem(i, 3, QTableWidgetItem(dt[11:19]))
            tot = QTableWidgetItem(f"{format_currency(r['total'])}"); tot.setForeground(QColor(AMBER)); tot.setTextAlignment(R); self.vr_table.setItem(i, 4, tot)
            sc = sc_map.get(r["status"], MUTED); stat = QTableWidgetItem(r["status"].capitalize()); stat.setForeground(QColor(sc)); stat.setTextAlignment(C); self.vr_table.setItem(i, 5, stat)
        self._vr_pg_label.setText(f"Page {self._vr_pg_page + 1} of {pages}  ({total} receipts)")
        self._vr_pg_prev.setEnabled(self._vr_pg_page > 0)
        self._vr_pg_next.setEnabled(self._vr_pg_page < pages - 1)

    def _vr_prev_page(self):
        if self._vr_pg_page > 0:
            self._vr_pg_page -= 1
            self._vr_load(self._vr_pg_search, self._vr_pg_status)

    def _vr_next_page(self):
        self._vr_pg_page += 1
        self._vr_load(self._vr_pg_search, self._vr_pg_status)

    def _vr_search_fn(self):
        self._vr_pg_page = 0
        sf = "completed" if self.vr_status_filter.currentIndex()==0 else ""
        self._vr_load(search=self.vr_search.text().strip(), status_filter=sf)

    def _vr_on_row_selected(self):
        row = self.vr_table.currentRow(); item = self.vr_table.item(row, 0)
        if not item: return
        receipt = get_receipt_by_id(item.data(Qt.ItemDataRole.UserRole))
        if not receipt: return
        self._vr_selected_tx_id=receipt["id"]; self._vr_selected_tx_status=receipt["status"]; self._vr_items_data=receipt.get("items",[])
        u = get_user_by_id(receipt["user_id"]); cname = u["full_name"] if u else "—"
        self.vr_receipt_title.setText(f"Receipt {receipt['receipt_number']}")
        self.vr_receipt_meta.setText(f"Cashier: {cname}\nDate: {str(receipt['created_at'])[:16]}\nStatus: {receipt['status'].capitalize()}")
        is_partial = self.vr_refund_mode.currentIndex()==1
        self.vr_items_table.setRowCount(len(self._vr_items_data))
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        from core.db_checkout import get_remaining_refundable_qty
        for r, it in enumerate(self._vr_items_data):
            remaining = get_remaining_refundable_qty(it["id"])
            self.vr_items_table.setItem(r, 0, QTableWidgetItem(it["product_name"]))
            sold = QTableWidgetItem(str(it["quantity"])); sold.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vr_items_table.setItem(r, 1, sold)

            qty_spin = QSpinBox()
            qty_spin.setMinimum(0); qty_spin.setMaximum(remaining)
            qty_spin.setValue(remaining)  # default: refund everything left on this line
            qty_spin.setEnabled(is_partial and remaining > 0)
            if remaining == 0:
                qty_spin.setToolTip("Already fully refunded/voided — nothing left on this line.")
            qty_spin.valueChanged.connect(self._vr_update_selected_amount)
            self.vr_items_table.setCellWidget(r, 2, qty_spin)

            pi = QTableWidgetItem(f"{format_currency(it['unit_price'])}"); pi.setTextAlignment(R); self.vr_items_table.setItem(r, 3, pi)
            ti = QTableWidgetItem(f"{format_currency(it['line_total'])}"); ti.setForeground(QColor(GREEN)); ti.setTextAlignment(R)
            self.vr_items_table.setItem(r, 4, ti)  # updated live in _vr_update_selected_amount
        self.vr_totals.setText(f"Subtotal: {format_currency(receipt['subtotal'])}  |  GCT: {format_currency(receipt['gct_amount'])}  |  <b>Total: {format_currency(receipt['total'])}</b>")
        self.vr_totals.setTextFormat(Qt.TextFormat.RichText)
        self.vr_status_banner.setVisible(False); self.vr_reason.clear(); self._vr_update_buttons()

    def _vr_on_mode_changed(self):
        is_partial = self.vr_refund_mode.currentIndex()==1
        from core.db_checkout import get_remaining_refundable_qty
        for r, it in enumerate(self._vr_items_data):
            spin = self.vr_items_table.cellWidget(r, 2)
            if not spin: continue
            remaining = get_remaining_refundable_qty(it["id"])
            spin.setEnabled(is_partial and remaining > 0)
            if not is_partial:
                # Full refund — always request everything remaining on every line
                spin.setValue(remaining)
        self._vr_update_selected_amount()

    def _vr_update_selected_amount(self):
        if not self._vr_items_data:
            self.vr_amount_lbl.setText(""); return
        R = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        total = 0.0
        for r, it in enumerate(self._vr_items_data):
            spin = self.vr_items_table.cellWidget(r, 2)
            qty = spin.value() if spin else 0
            # Same proportional formula the backend uses (db_checkout._validate_and_price_items)
            line_amount = round((it["line_total"] / it["quantity"]) * qty, 2) if qty else 0.0
            total += line_amount
            cell = self.vr_items_table.item(r, 4)
            if cell:
                cell.setText(f"{format_currency(line_amount)}")
        self.vr_amount_lbl.setText(f"Refund total: {format_currency(total)}")

    def _vr_update_buttons(self):
        ok = self._vr_selected_tx_id is not None and self._vr_selected_tx_status=="completed" and bool(self.vr_reason.text().strip())
        self.vr_void_btn.setEnabled(ok); self.vr_refund_btn.setEnabled(ok)

    def _vr_do_void(self):
        reason = self.vr_reason.text().strip()
        if not reason: QMessageBox.warning(self, "Reason Required", "Please enter a reason."); return
        reply = QMessageBox.question(self, "Confirm Void", f"Void receipt #{self._vr_selected_tx_id}?\nReason: {reason}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        try:
            voided = void_receipt(self._vr_selected_tx_id, self.user["id"], reason)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot Void", str(e))
            self._vr_on_row_selected()
            return
        if voided:
            # Increment stock for all items in the voided receipt
            from core.db_config import get_bool
            if get_bool("stock_tracking", False):
                from core.db_products import increment_stock
                for it in (self._vr_items_data or []):
                    if it.get("product_id"):
                        increment_stock(it["product_id"], it["quantity"])
            # Print void notice
            receipt = get_receipt_by_id(self._vr_selected_tx_id)
            if receipt:
                from core.db_checkout import get_refunds_for_receipt
                refunds = get_refunds_for_receipt(receipt["id"])
                refund  = refunds[0] if refunds else {"reason": reason}
                from utils.print_manager import print_void
                print_void(receipt, refund, voided_by_user=self.user, parent=self)
            self._vr_selected_tx_status="voided"; self.vr_void_btn.setEnabled(False); self.vr_refund_btn.setEnabled(False)
            self.vr_status_banner.setText(f"✓  Receipt #{self._vr_selected_tx_id} voided."); self.vr_status_banner.setStyleSheet(f"color:{RED};font-size:12px;font-weight:600;"); self.vr_status_banner.setVisible(True)
            self._vr_search_fn()
        else: QMessageBox.critical(self, "Failed", "Could not void this receipt.")

    def _vr_do_refund(self):
        reason = self.vr_reason.text().strip()
        if not reason: QMessageBox.warning(self, "Reason Required", "Please enter a reason."); return
        is_partial = self.vr_refund_mode.currentIndex()==1
        items = []
        amount = 0.0
        for r, it in enumerate(self._vr_items_data):
            spin = self.vr_items_table.cellWidget(r, 2)
            qty = spin.value() if spin else 0
            if qty > 0:
                items.append({"receipt_item_id": it["id"], "quantity": qty})
                amount += round((it["line_total"] / it["quantity"]) * qty, 2)
        if not items: QMessageBox.warning(self, "No Items", "Select at least one item with a refund quantity."); return
        mode = "Partial" if is_partial else "Full"
        reply = QMessageBox.question(self, f"Confirm {mode} Refund", f"{mode} refund — {format_currency(amount)}\nReason: {reason}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        rtype = "partial" if is_partial else "full"
        try:
            ok = refund_receipt(self._vr_selected_tx_id, self.user["id"], reason, items, refund_type=rtype)
        except ValueError as e:
            # Reconciliation check caught an over-refund — e.g. two supervisors
            # working the same receipt at once. Surface it plainly and refresh
            # so the quantities shown reflect what's actually still refundable.
            QMessageBox.warning(self, "Cannot Process Refund", str(e))
            self._vr_on_row_selected()
            return
        if ok:
            # Increment stock for refunded items (using the quantities actually submitted)
            from core.db_config import get_bool
            if get_bool("stock_tracking", False):
                from core.db_products import increment_stock
                by_id = {it["id"]: it for it in self._vr_items_data}
                for entry in items:
                    src = by_id.get(entry["receipt_item_id"])
                    if src and src.get("product_id"):
                        increment_stock(src["product_id"], entry["quantity"])
            # Print refund receipt
            receipt = get_receipt_by_id(self._vr_selected_tx_id)
            if receipt:
                from core.db_checkout import get_refunds_for_receipt
                refunds = get_refunds_for_receipt(receipt["id"])
                refund_rec = refunds[0] if refunds else {"reason": reason, "amount": amount, "refund_type": rtype}
                from utils.print_manager import print_refund
                print_refund(receipt, refund_rec, refunded_by_user=self.user, parent=self)
            self.vr_void_btn.setEnabled(False); self.vr_refund_btn.setEnabled(False)
            self.vr_status_banner.setText(f"✓  {mode} refund of {format_currency(amount)} issued."); self.vr_status_banner.setStyleSheet(f"color:{AMBER};font-size:12px;font-weight:600;"); self.vr_status_banner.setVisible(True)
            self._vr_search_fn()
        else: QMessageBox.critical(self, "Failed", "Could not process refund.")

    # ================================================================
    # QUICK KEYS TAB
    # ================================================================

    def _build_stock_tab(self):
        from ui.supervisor.stock_tab import StockTab
        return StockTab(self.user, parent=self)

    def _build_price_tag_tab(self):
        from ui.supervisor.price_tag_tab import PriceTagTab
        return PriceTagTab(self.user, parent=self)

    def _build_quickkeys_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(10)
        hint = QLabel("Assign a product to each F-key (F1–F8). Start typing a product name to search.")
        hint.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;"); lay.addWidget(hint)
        self._qk_inputs = []
        for k in get_quick_keys():
            row = QHBoxLayout(); row.setSpacing(10)
            badge = QLabel(f"F{k['slot']}"); badge.setFixedSize(40,32); badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"background:{DARK_CARD};color:{AMBER};border-radius:6px;font-size:11px;font-weight:700;")
            inp = QLineEdit(); inp.setFixedHeight(34)
            inp.setPlaceholderText("Search products…")
            inp.setText(f"{k['product_name']} ({format_currency(k['product_price'])})" if k.get("product_name") else "")
            inp.setStyleSheet(self._input_style(accent=bool(k.get("product_name"))))
            inp.setProperty("slot", k["slot"]); inp.setProperty("product_id", k.get("product_id"))
            row.addWidget(badge); row.addWidget(inp, stretch=1)
            lay.addLayout(row); self._qk_inputs.append(inp)
        lay.addStretch()
        save_btn = QPushButton("💾  Save Quick Keys"); save_btn.setFixedHeight(42)
        save_btn.setStyleSheet(self._accent_btn()); save_btn.clicked.connect(self._qk_save); lay.addWidget(save_btn)
        return w

    def _qk_save(self):
        assignments = []
        for inp in self._qk_inputs:
            slot = inp.property("slot"); pid = inp.property("product_id"); text = inp.text().strip()
            if not pid and text:
                results = get_products(search=text, limit=1)
                if results: pid = results[0]["id"]; inp.setProperty("product_id", pid)
            # Only slot + product_id are stored — name/price are resolved
            # live from products.db on every read, never snapshotted here.
            assignments.append({"slot": slot, "product_id": pid})
        save_quick_keys(assignments)
        QMessageBox.information(self, "Saved", "Quick keys saved successfully.")

    # ================================================================
    # CLOCK + LOGOUT
    # ================================================================

    def _start_clock(self):
        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000); self._tick()

    def _tick(self):
        n = QDateTime.currentDateTime()
        self._clock.setText(n.toString("dd MMM yyyy") + "   " + n.toString("hh:mm:ss AP"))

    def _handle_logout(self):
        reply = QMessageBox.question(self, "Logout", "Are you sure you want to logout?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.logout_requested.emit(); self.force_close()

    # ================================================================
    # STYLE HELPERS
    # ================================================================

    def _table_style(self):
        return f"""
            QTableWidget{{background:{WHITE};border:none;font-size:12px;color:{DARK_CARD};}}
            QTableWidget::item{{padding:6px 8px;border-bottom:1px solid {BORDER_LIGHT};}}
            QTableWidget::item:hover{{background:{AMBER_LIGHTEST};}}
            QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}
            QHeaderView::section{{background:{DARK};color:{AMBER};font-size:11px;
            font-weight:700;padding:6px 8px;border:none;border-right:1px solid {DARK_4};}}
            QScrollBar:vertical{{background:{WARM_WHITE};width:6px;border-radius:3px;}}
            QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;}}
        """

    def _input_style(self, accent=False):
        b = AMBER if accent else BORDER
        return (
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {b};"
            f"border-radius:7px;padding:0 10px;font-size:12px;font-weight:400;outline:none;}}"
            f"QLineEdit:hover{{border-color:{AMBER_LIGHTEST if not accent else AMBER};}}"
            f"QLineEdit:focus{{border-color:{AMBER};background:#fffef9;}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
            f"QLineEdit:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}"
            f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {b};"
            f"border-radius:7px;padding:0 8px;font-size:12px;outline:none;}}"
            f"QSpinBox:hover{{border-color:{AMBER_LIGHTEST};}}"
            f"QSpinBox:focus{{border-color:{AMBER};}}"
        )

    def _combo_style(self):
        return (
            f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;font-weight:400;outline:none;}}"
            f"QComboBox:hover{{border-color:{AMBER_LIGHTEST};}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
            f"QComboBox::down-arrow{{width:10px;height:10px;}}"
            f"QComboBox QAbstractItemView{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};outline:none;"
            f"selection-background-color:{AMBER};selection-color:white;}}"
        )

    def _accent_btn(self):
        return (
            f"QPushButton{{background:{AMBER};color:{DARK};border:none;"
            f"border-radius:17px;font-size:12px;font-weight:700;padding:0 16px;outline:none;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};color:{DARK};}}"
            f"QPushButton:pressed{{background:{AMBER_DARK};color:{DARK};}}"
            f"QPushButton:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}"
        )

    def _outline_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{LABEL_TEXT};border:1.5px solid {BORDER};"
            f"border-radius:16px;font-size:11px;font-weight:600;padding:0 14px;outline:none;}}"
            f"QPushButton:hover{{background:{WARM_WHITE};color:{DARK_CARD};border-color:{AMBER};}}"
            f"QPushButton:pressed{{background:{BORDER_LIGHT};}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}"
        )
        return b

    def _danger_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{RED_LIGHT};color:{RED};border:none;"
            f"border-radius:16px;font-size:11px;font-weight:600;padding:0 14px;outline:none;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:pressed{{background:#7A1F1F;color:white;}}"
            f"QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};}}"
        )
        return b

    def _success_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{GREEN_LIGHT};color:{GREEN};border:none;"
            f"border-radius:16px;font-size:11px;font-weight:600;padding:0 14px;outline:none;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:pressed{{background:#134D28;color:white;}}"
            f"QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};}}"
        )
        return b

    def _icon_btn(self, icon, tooltip=""):
        b = QPushButton(icon); b.setFixedSize(34,34); b.setToolTip(tooltip); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{WARM_WHITE};color:{DARK_CARD};border:1.5px solid {BORDER};"
            f"border-radius:7px;font-size:14px;font-weight:700;outline:none;}}"
            f"QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}"
            f"QPushButton:pressed{{background:{AMBER_LIGHTEST};}}"
        )
        return b

    def _draw_product_icon(self, kind: str, color: str, size: int = 19):
        """Hand-painted icon (currently just 'clear') — same approach as
        ui/supervisor/price_tag_tab.py: a drawn glyph instead of a Unicode
        dingbat, since font-fallback for those isn't reliable everywhere."""
        from PyQt6.QtCore import QSize as _QSize
        from PyQt6.QtGui import QPainter, QPen, QIcon, QPixmap
        scale = 4
        s = size * scale
        pm = QPixmap(s, s); pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color)); pen.setWidthF(s * 0.12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = s * 0.22
        if kind == "clear":
            p.drawLine(int(m), int(m), int(s - m), int(s - m))
            p.drawLine(int(s - m), int(m), int(m), int(s - m))
        p.end()
        pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        return QIcon(pm)

    def _product_icon_btn(self, kind: str, tooltip: str = ""):
        from PyQt6.QtCore import QSize as _QSize
        b = QPushButton(); b.setFixedSize(36, 36)
        b.setToolTip(tooltip); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setIcon(self._draw_product_icon(kind, DARK_CARD)); b.setIconSize(_QSize(16, 16))
        b.setStyleSheet(
            f"QPushButton{{background:{WARM_WHITE};border:1.5px solid {BORDER};border-radius:7px;outline:none;}}"
            f"QPushButton:hover{{border-color:{AMBER};background:{AMBER_LIGHTEST};}}"
            f"QPushButton:pressed{{background:{BORDER_LIGHT};}}"
        )
        return b

    def _field(self, label, placeholder, uppercase=True):
        lbl = self._flabel(label)
        if uppercase:
            inp = self.make_upper_input(placeholder)
        else:
            inp = QLineEdit(); inp.setPlaceholderText(placeholder); inp.setFixedHeight(34)
        inp.setStyleSheet(self._input_style()); return lbl, inp

    def _flabel(self, text):
        l = QLabel(text); l.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;"); return l

    def _section_lbl(self, text):
        l = QLabel(text.upper()); l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;"); return l

    def _toggle(self, label, checked=False):
        cb = QCheckBox(label); cb.setChecked(checked)
        cb.setStyleSheet(f"QCheckBox{{color:{DARK_CARD};font-size:12px;font-weight:500;}}QCheckBox::indicator{{width:16px;height:16px;border:1px solid {BORDER};border-radius:3px;background:{WHITE};}}QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}")
        return cb
