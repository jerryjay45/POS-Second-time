"""
ui/supervisor/supervisor_window.py
Supervisor dashboard — Products, Reports, Transactions, Void/Refund, Quick Keys.
Adapted from prototype layout and functions with amber/dark theme.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QCheckBox, QAbstractItemView,
    QMessageBox, QScrollArea, QSplitter, QSpinBox, QDialog, QRadioButton,
)
from PyQt6.QtCore  import Qt, QTimer, QDateTime, pyqtSignal
from PyQt6.QtGui   import QColor, QDoubleValidator

from ui.base_window  import BaseWindow
from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_4, DARK_CARD,
    WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN, GREEN_LIGHT, BLUE,
)
from core.db_products import (
    get_products, get_product_by_id, add_product, update_product,
    delete_product, get_groups, add_group,
    get_price_groups, add_price_group, update_price_group,
    count_products, cascade_single_cost_to_cases, recalculate_all_cases,
    adjust_stock,
    get_case_groups, get_case_group_by_id,
    add_case_group, update_case_group, adjust_case_group_stock,
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
        # TODO: Void/Refund tab pulled out early — added before the rest of
        # the workflow was stable. Underlying module (ui/supervisor/
        # void_refund_tab.py) is untouched; re-enable by uncommenting below.
        # from ui.supervisor.void_refund_tab import VoidRefundTab
        # self._void_refund_tab = VoidRefundTab(user=self.user, parent=self)
        # self.tabs.addTab(self._void_refund_tab, "↩  Void / Refund")
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
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(10)
        lay.addWidget(self._build_product_list(), stretch=3)
        lay.addWidget(self._build_product_form(), stretch=2)
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

        refresh_btn = self._outline_btn("↻  Refresh")
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(lambda: (setattr(self, '_pg_page', 0), self._load_products(self.product_search.text())))

        recalc_btn = QPushButton("⟳ Recalc Cases")
        recalc_btn.setFixedHeight(36)
        recalc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        recalc_btn.setToolTip("Recalculate all case product prices from their linked single products")
        recalc_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER_DARK};border:1.5px solid {AMBER};"
            f"border-radius:7px;font-size:12px;font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{background:{AMBER_LIGHTEST};}}"
        )
        recalc_btn.clicked.connect(self._recalculate_cases)

        add_btn = QPushButton("＋  Add Product"); add_btn.setFixedHeight(36)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(self._accent_btn())
        add_btn.clicked.connect(self._new_product_form)

        tb.addWidget(self.product_search, stretch=1)
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
        self.product_table.setColumnWidth(2, 80)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.product_table.setColumnWidth(3, 80)
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

    def _build_product_form(self):
        scroll = QScrollArea(); scroll.setMinimumWidth(340); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:1px solid {BORDER};border-radius:10px;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(fw); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        # ── Title ─────────────────────────────────────────────────────
        self.form_title = QLabel("➕  Add Product")
        self.form_title.setStyleSheet(f"color:{DARK_CARD};font-size:16px;font-weight:700;padding-bottom:2px;")
        lay.addWidget(self.form_title)
        lay.addSpacing(2)

        def _divider():
            d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
            d.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
            return d

        def _section(title):
            l = QLabel(title.upper())
            l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
            return l

        # ── Section 1: Identity ───────────────────────────────────────
        lay.addWidget(_section("Identity"))
        self.f_barcode = self._field("Barcode", "Scan or type barcode")
        self.f_name    = self._field("Name",    "e.g. COCA COLA 330ML")
        for lbl, inp in [self.f_barcode, self.f_name]:
            lay.addWidget(lbl); lay.addWidget(inp)

        # ── Section 2: Pricing ────────────────────────────────────────
        lay.addSpacing(4)
        lay.addWidget(_divider())
        lay.addSpacing(2)
        lay.addWidget(_section("Pricing"))

        # Cost (full width)
        self.f_cost = self._field("Cost", "0.00")
        self.f_cost[1].setValidator(QDoubleValidator(0, 999999, 2))
        self.f_cost[1].textChanged.connect(self._calc_selling_price)
        lay.addWidget(self.f_cost[0]); lay.addWidget(self.f_cost[1])

        # Selling Price (full width, read-only display)
        lay.addWidget(self._flabel("Selling Price"))
        self.f_price = QLineEdit(); self.f_price.setReadOnly(True); self.f_price.setFixedHeight(36)
        self.f_price.setStyleSheet(f"QLineEdit{{background:#0d1a10;color:{GREEN};border:1px solid #1a3a20;border-radius:6px;padding:0 10px;font-size:14px;font-weight:700;}}")
        self.f_price_hint = QLabel(""); self.f_price_hint.setStyleSheet(f"color:{MUTED};font-size:10px;")
        lay.addWidget(self.f_price); lay.addWidget(self.f_price_hint)

        lay.addSpacing(2)
        lay.addWidget(self._flabel("Product Group"))
        self.f_group = QComboBox(); self.f_group.setStyleSheet(self._combo_style())
        self.f_group.currentIndexChanged.connect(self._calc_selling_price)
        self._populate_groups(); lay.addWidget(self.f_group)

        # Alias + Variant side by side
        grp_row = QHBoxLayout(); grp_row.setSpacing(8)
        alias_col   = QVBoxLayout(); alias_col.setSpacing(4)
        variant_col = QVBoxLayout(); variant_col.setSpacing(4)
        alias_col.addWidget(self._flabel("Alias Group"))
        from ui.shared.searchable_group_combo import SearchableGroupCombo
        self.f_alias_group = SearchableGroupCombo("alias")
        alias_col.addWidget(self.f_alias_group)
        variant_col.addWidget(self._flabel("Variant Group"))
        self.f_variant_group = SearchableGroupCombo("variant")
        variant_col.addWidget(self.f_variant_group)
        grp_row.addLayout(alias_col); grp_row.addLayout(variant_col)
        lay.addLayout(grp_row)

        # ── Section 3: Discounts ──────────────────────────────────────
        lay.addSpacing(4)
        lay.addWidget(_divider())
        lay.addSpacing(2)
        lay.addWidget(_section("Discounts"))
        disc_row = QHBoxLayout(); disc_row.setSpacing(8)
        d1_col = QVBoxLayout(); d1_col.setSpacing(4)
        d2_col = QVBoxLayout(); d2_col.setSpacing(4)

        d1_col.addWidget(self._flabel("Discount Level 1"))
        self.f_disc1 = QComboBox(); self.f_disc1.setStyleSheet(self._combo_style())
        self._populate_discount_levels(self.f_disc1); d1_col.addWidget(self.f_disc1)
        self.f_disc1_custom = self._build_custom_disc_inputs("1")
        self.f_disc1_custom.setVisible(False)
        d1_col.addWidget(self.f_disc1_custom)
        self.f_disc1.currentIndexChanged.connect(
            lambda: self.f_disc1_custom.setVisible(
                self.f_disc1.currentData() == "custom"))

        d2_col.addWidget(self._flabel("Discount Level 2"))
        self.f_disc2 = QComboBox(); self.f_disc2.setStyleSheet(self._combo_style())
        self._populate_discount_levels(self.f_disc2); d2_col.addWidget(self.f_disc2)
        self.f_disc2_custom = self._build_custom_disc_inputs("2")
        self.f_disc2_custom.setVisible(False)
        d2_col.addWidget(self.f_disc2_custom)
        self.f_disc2.currentIndexChanged.connect(
            lambda: self.f_disc2_custom.setVisible(
                self.f_disc2.currentData() == "custom"))

        disc_row.addLayout(d1_col); disc_row.addLayout(d2_col)
        lay.addLayout(disc_row)

        # ── Section 4: Flags ──────────────────────────────────────────
        lay.addSpacing(4)
        lay.addWidget(_divider())
        lay.addSpacing(2)
        lay.addWidget(_section("Flags"))
        flags_row = QHBoxLayout(); flags_row.setSpacing(16)
        self.t_gct  = self._toggle("GCT Applicable", True)
        self.t_case = self._toggle("Case Item")
        self.t_case.stateChanged.connect(self._on_case_toggled)
        flags_row.addWidget(self.t_gct); flags_row.addWidget(self.t_case); flags_row.addStretch()
        lay.addLayout(flags_row)

        # ── Case Box — shown when "Case Item" is ticked ─────────────
        self.case_box = QFrame(); self.case_box.setVisible(False)
        self.case_box.setStyleSheet(f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};border-radius:6px;")
        cb_lay = QVBoxLayout(self.case_box); cb_lay.setContentsMargins(10,10,10,10); cb_lay.setSpacing(6)

        # Mode toggle — radio buttons
        cb_lay.addWidget(self._flabel("Case Mode"))
        mode_row = QHBoxLayout(); mode_row.setSpacing(16)
        self.case_mode_linked = QRadioButton("Linked to specific product")
        self.case_mode_pool   = QRadioButton("Shared pool")
        self.case_mode_linked.setChecked(True)
        for rb in (self.case_mode_linked, self.case_mode_pool):
            rb.setStyleSheet(f"color:{DARK_CARD};font-size:12px;")
            mode_row.addWidget(rb)
        mode_row.addStretch()
        cb_lay.addLayout(mode_row)
        self.case_mode_linked.toggled.connect(self._on_case_mode_changed)

        # ── Mode 1 panel: linked to a specific single product ─────────
        self.case_mode1_frame = QFrame()
        self.case_mode1_frame.setStyleSheet("background:transparent;border:none;")
        m1_lay = QVBoxLayout(self.case_mode1_frame); m1_lay.setContentsMargins(0,4,0,0); m1_lay.setSpacing(6)
        m1_lay.addWidget(self._flabel("Parent Single Product"))
        from ui.shared.searchable_product_combo import SearchableProductCombo
        self.f_case_parent = SearchableProductCombo()
        self.f_case_parent.selectionChanged.connect(lambda pid, name: self._on_case_parent_changed())
        m1_lay.addWidget(self.f_case_parent)
        self.f_case_cost_hint = QLabel("")
        self.f_case_cost_hint.setStyleSheet(f"color:{MUTED};font-size:10px;")
        m1_lay.addWidget(self.f_case_cost_hint)
        m1_lay.addWidget(self._flabel("Units per Case"))
        self.f_case_qty = QSpinBox(); self.f_case_qty.setMinimum(1); self.f_case_qty.setMaximum(9999)
        self.f_case_qty.setStyleSheet(self._input_style())
        self.f_case_qty.valueChanged.connect(self._on_case_parent_changed)
        m1_lay.addWidget(self.f_case_qty)
        # Restock (Mode 1) — converts cases to parent units
        m1_lay.addWidget(_divider())
        m1_lay.addWidget(self._flabel("Restock via Case"))
        self.case_stock_lbl = QLabel("Select a parent product to see stock.")
        self.case_stock_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:11px;font-weight:600;")
        self.case_stock_lbl.setWordWrap(True)
        m1_lay.addWidget(self.case_stock_lbl)
        m1_restock_row = QHBoxLayout(); m1_restock_row.setSpacing(6)
        self.case_restock_qty = QSpinBox()
        self.case_restock_qty.setMinimum(1); self.case_restock_qty.setMaximum(9999)
        self.case_restock_qty.setStyleSheet(self._input_style())
        m1_restock_row.addWidget(self.case_restock_qty, stretch=1)
        self.case_restock_add_btn = QPushButton("＋  Add Cases")
        self.case_restock_add_btn.setFixedHeight(30); self.case_restock_add_btn.setEnabled(False)
        self.case_restock_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.case_restock_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};border:1.5px solid {GREEN};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}")
        self.case_restock_add_btn.clicked.connect(self._case_restock_add)
        self.case_restock_remove_btn = QPushButton("−  Remove")
        self.case_restock_remove_btn.setFixedHeight(30); self.case_restock_remove_btn.setEnabled(False)
        self.case_restock_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.case_restock_remove_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1.5px solid {RED};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}")
        self.case_restock_remove_btn.clicked.connect(self._case_restock_remove)
        m1_restock_row.addWidget(self.case_restock_add_btn)
        m1_restock_row.addWidget(self.case_restock_remove_btn)
        m1_lay.addLayout(m1_restock_row)
        self.case_restock_feedback = QLabel("")
        self.case_restock_feedback.setStyleSheet(f"font-size:10px;font-weight:600;")
        m1_lay.addWidget(self.case_restock_feedback)
        cb_lay.addWidget(self.case_mode1_frame)

        # ── Mode 2 panel: shared pool ─────────────────────────────────
        self.case_mode2_frame = QFrame(); self.case_mode2_frame.setVisible(False)
        self.case_mode2_frame.setStyleSheet("background:transparent;border:none;")
        m2_lay = QVBoxLayout(self.case_mode2_frame); m2_lay.setContentsMargins(0,4,0,0); m2_lay.setSpacing(6)
        # Case group picker + inline create
        m2_lay.addWidget(self._flabel("Case Group"))
        m2_grp_row = QHBoxLayout(); m2_grp_row.setSpacing(6)
        self.f_case_group_combo = QComboBox()
        self.f_case_group_combo.setStyleSheet(self._input_style())
        self.f_case_group_combo.setMinimumHeight(32)
        self.f_case_group_combo.currentIndexChanged.connect(self._on_case_group_changed)
        m2_grp_row.addWidget(self.f_case_group_combo, stretch=1)
        new_grp_btn = QPushButton("＋")
        new_grp_btn.setFixedSize(32, 32)
        new_grp_btn.setToolTip("Create a new case group")
        new_grp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_grp_btn.setStyleSheet(
            f"QPushButton{{background:{AMBER};color:white;border:none;"
            f"border-radius:6px;font-size:16px;font-weight:700;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};}}")
        new_grp_btn.clicked.connect(self._create_case_group)
        m2_grp_row.addWidget(new_grp_btn)
        m2_lay.addLayout(m2_grp_row)
        # Group info: cost, price, pool stock
        self.case_grp_info_lbl = QLabel("")
        self.case_grp_info_lbl.setStyleSheet(f"color:{MUTED};font-size:10px;")
        self.case_grp_info_lbl.setWordWrap(True)
        m2_lay.addWidget(self.case_grp_info_lbl)
        # Units per case (shared with mode 1 spinbox but shown here too)
        m2_lay.addWidget(self._flabel("Units per Case (for this product)"))
        self.f_case_qty2 = QSpinBox(); self.f_case_qty2.setMinimum(1); self.f_case_qty2.setMaximum(9999)
        self.f_case_qty2.setStyleSheet(self._input_style())
        m2_lay.addWidget(self.f_case_qty2)
        # Pool restock
        m2_lay.addWidget(_divider())
        m2_lay.addWidget(self._flabel("Restock Pool"))
        self.pool_stock_lbl = QLabel("Select a case group to see pool stock.")
        self.pool_stock_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:11px;font-weight:600;")
        self.pool_stock_lbl.setWordWrap(True)
        m2_lay.addWidget(self.pool_stock_lbl)
        m2_restock_row = QHBoxLayout(); m2_restock_row.setSpacing(6)
        self.pool_restock_qty = QSpinBox()
        self.pool_restock_qty.setMinimum(1); self.pool_restock_qty.setMaximum(9999)
        self.pool_restock_qty.setStyleSheet(self._input_style())
        m2_restock_row.addWidget(self.pool_restock_qty, stretch=1)
        self.pool_restock_add_btn = QPushButton("＋  Add to Pool")
        self.pool_restock_add_btn.setFixedHeight(30); self.pool_restock_add_btn.setEnabled(False)
        self.pool_restock_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pool_restock_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};border:1.5px solid {GREEN};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}")
        self.pool_restock_add_btn.clicked.connect(self._pool_restock_add)
        self.pool_restock_remove_btn = QPushButton("−  Remove")
        self.pool_restock_remove_btn.setFixedHeight(30); self.pool_restock_remove_btn.setEnabled(False)
        self.pool_restock_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pool_restock_remove_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1.5px solid {RED};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}")
        self.pool_restock_remove_btn.clicked.connect(self._pool_restock_remove)
        m2_restock_row.addWidget(self.pool_restock_add_btn)
        m2_restock_row.addWidget(self.pool_restock_remove_btn)
        m2_lay.addLayout(m2_restock_row)
        self.pool_restock_feedback = QLabel("")
        self.pool_restock_feedback.setStyleSheet(f"font-size:10px;font-weight:600;")
        m2_lay.addWidget(self.pool_restock_feedback)
        cb_lay.addWidget(self.case_mode2_frame)

        lay.addWidget(self.case_box)

        # ── Section 5: Stock (edit only) ──────────────────────────────
        lay.addSpacing(4)
        lay.addWidget(_divider())
        self.stock_section = QFrame()
        self.stock_section.setVisible(False)
        self.stock_section.setStyleSheet(f"background:transparent;")
        sl = QVBoxLayout(self.stock_section); sl.setContentsMargins(0,0,0,0); sl.setSpacing(6)
        sl.addWidget(_section("Stock Adjustment"))

        self.stock_current_lbl = QLabel("Current stock: —")
        self.stock_current_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:600;")
        sl.addWidget(self.stock_current_lbl)

        adj_row = QHBoxLayout(); adj_row.setSpacing(8)
        self.stock_qty = QSpinBox(); self.stock_qty.setMinimum(1); self.stock_qty.setMaximum(99999)
        self.stock_qty.setValue(1); self.stock_qty.setFixedHeight(34)
        self.stock_qty.setStyleSheet(self._input_style())
        self.stock_reason = QComboBox(); self.stock_reason.setFixedHeight(34)
        self.stock_reason.setStyleSheet(self._combo_style())
        for r in ["Restock", "Damaged", "Correction", "Other"]:
            self.stock_reason.addItem(r)
        adj_row.addWidget(self.stock_qty, stretch=1)
        adj_row.addWidget(self.stock_reason, stretch=2)
        sl.addLayout(adj_row)

        stock_btn_row = QHBoxLayout(); stock_btn_row.setSpacing(8)
        self.stock_add_btn = QPushButton("＋  Add Stock"); self.stock_add_btn.setFixedHeight(32)
        self.stock_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stock_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};border:1.5px solid {GREEN};"
            f"border-radius:7px;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
        )
        self.stock_add_btn.clicked.connect(self._stock_add)
        self.stock_remove_btn = QPushButton("−  Remove"); self.stock_remove_btn.setFixedHeight(32)
        self.stock_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stock_remove_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1.5px solid {RED};"
            f"border-radius:7px;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
        )
        self.stock_remove_btn.clicked.connect(self._stock_remove)
        stock_btn_row.addWidget(self.stock_add_btn, stretch=1)
        stock_btn_row.addWidget(self.stock_remove_btn, stretch=1)
        sl.addLayout(stock_btn_row)
        lay.addWidget(self.stock_section)

        lay.addStretch()

        # ── Bottom buttons ────────────────────────────────────────────
        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setStyleSheet(f"QPushButton{{background:{DARK_CARD};color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;}}QPushButton:hover{{background:#444;}}")
        self.cancel_btn.clicked.connect(self._new_product_form)
        self.save_btn = QPushButton("Save Product"); self.save_btn.setFixedHeight(40)
        self.save_btn.setStyleSheet(self._accent_btn()); self.save_btn.clicked.connect(self._save_product)
        btn_row.addWidget(self.cancel_btn, stretch=1); btn_row.addWidget(self.save_btn, stretch=2)
        lay.addLayout(btn_row)

        scroll.setWidget(fw)
        return scroll

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
            tags = []
            if p["gct_applicable"]: tags.append("GCT")
            if p["is_case"]:        tags.append("CASE")
            tags_str   = "  ·  ".join(tags) if tags else "—"
            tags_color = AMBER_DARK if tags else MUTED
            self.product_table.setItem(row, 0, cell(p["name"]))
            self.product_table.setItem(row, 1, cell(p["barcode"], MUTED))
            self.product_table.setItem(row, 2, cell(f"${p['cost']:.2f}", AMBER_DARK, R))
            self.product_table.setItem(row, 3, cell(f"${p['selling_price']:.2f}", GREEN, R))
            self.product_table.setItem(row, 4, cell(tags_str, tags_color, C))
            act = QWidget(); al = QHBoxLayout(act)
            al.setContentsMargins(4, 2, 4, 2); al.setSpacing(4)
            for label, color, cb in [
                ("Edit", AMBER, lambda _, pid=p["id"]: self._edit_product(pid)),
                ("✕",    RED,   lambda _, pid=p["id"]: self._delete_product(pid)),
            ]:
                b = QPushButton(label); b.setFixedHeight(26)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{color};border:1px solid {color};"
                    f"border-radius:5px;font-size:12px;font-weight:600;padding:0 8px;}}"
                    f"QPushButton:hover{{background:{color};color:white;}}"
                )
                b.clicked.connect(cb); al.addWidget(b)
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

    def _new_product_form(self):
        self._editing_product_id = None
        self.form_title.setText("➕  Add Product")
        for _, inp in [self.f_barcode, self.f_name, self.f_cost]:
            inp.clear()
        self.f_group.setCurrentIndex(0)
        self.f_alias_group.clear_value()
        self.f_variant_group.clear_value()
        self.f_disc1.setCurrentIndex(0); self.f_disc2.setCurrentIndex(0)
        self.f_disc1_custom.setVisible(False); self.f_disc2_custom.setVisible(False)
        self.f_disc1_qty.setValue(1); self.f_disc1_pct.setValue(5.0)
        self.f_disc2_qty.setValue(1); self.f_disc2_pct.setValue(10.0)
        self.t_gct.setChecked(True); self.t_case.setChecked(False)
        self.f_price.clear(); self.f_price_hint.clear()
        self.stock_section.setVisible(False)
        # Mode 1 reset
        self.f_case_parent.clear_value()
        self.f_case_parent.exclude_id(None)
        self.f_case_cost_hint.setText("")
        self.case_restock_qty.setValue(1)
        self.case_restock_feedback.setText("")
        # Mode 2 reset
        self.case_mode_linked.setChecked(True)
        self.f_case_qty2.setValue(1)
        self.pool_restock_qty.setValue(1)
        self.pool_restock_feedback.setText("")
        self.f_group.setEnabled(True)
        self.f_group.setToolTip("")

    def _edit_product(self, pid: int):
        p = get_product_by_id(pid)
        if not p: return
        self._editing_product_id = pid
        self.form_title.setText("✎  Edit Product")
        self.f_barcode[1].setText(p["barcode"])
        self.f_name[1].setText(p["name"])
        self.f_cost[1].setText(str(p["cost"]))
        self.f_price.setText(f"${p['selling_price']:.2f}")
        self.t_gct.setChecked(bool(p["gct_applicable"]))
        self.t_case.setChecked(bool(p["is_case"]))
        if p["is_case"]:
            is_pool = bool(p.get("case_group_id"))
            # Set mode toggle before populating panels
            self.case_mode_linked.setChecked(not is_pool)
            self.case_mode_pool.setChecked(is_pool)
            if is_pool:
                # Mode 2 — shared pool
                self.f_case_qty2.setValue(p.get("case_qty") or 1)
                self._populate_case_group_combo(select_id=p.get("case_group_id"))
                self.f_group.setEnabled(True)
                self.f_group.setToolTip("")
            else:
                # Mode 1 — linked to specific parent
                if p.get("case_qty"):
                    self.f_case_qty.setValue(p["case_qty"])
                self._populate_case_parents(select_id=p.get("case_product_id"))
                if p.get("case_product_id"):
                    self.f_group.setEnabled(False)
                    self.f_group.setToolTip(
                        "Group is inherited from the parent single product.\n"
                        "Change the parent to change the group."
                    )
                else:
                    self.f_group.setEnabled(True)
                    self.f_group.setToolTip("")
        for i in range(self.f_group.count()):
            if self.f_group.itemData(i) == p.get("group_id"):
                self.f_group.setCurrentIndex(i); break
        self.f_alias_group.set_value(p.get("alias_group_id"))
        self.f_variant_group.set_value(p.get("variant_group_id"))

        # Discount level 1 — named level or custom inline
        if p.get("inline_disc1_qty") and p.get("inline_disc1_pct"):
            # Select "Custom…" and fill inputs
            for i in range(self.f_disc1.count()):
                if self.f_disc1.itemData(i) == "custom":
                    self.f_disc1.setCurrentIndex(i); break
            self.f_disc1_qty.setValue(int(p["inline_disc1_qty"]))
            self.f_disc1_pct.setValue(float(p["inline_disc1_pct"]))
            self.f_disc1_custom.setVisible(True)
        else:
            self.f_disc1_custom.setVisible(False)
            for i in range(self.f_disc1.count()):
                if self.f_disc1.itemData(i) == p.get("discount_level1"):
                    self.f_disc1.setCurrentIndex(i); break

        # Discount level 2 — named level or custom inline
        if p.get("inline_disc2_qty") and p.get("inline_disc2_pct"):
            for i in range(self.f_disc2.count()):
                if self.f_disc2.itemData(i) == "custom":
                    self.f_disc2.setCurrentIndex(i); break
            self.f_disc2_qty.setValue(int(p["inline_disc2_qty"]))
            self.f_disc2_pct.setValue(float(p["inline_disc2_pct"]))
            self.f_disc2_custom.setVisible(True)
        else:
            self.f_disc2_custom.setVisible(False)
            for i in range(self.f_disc2.count()):
                if self.f_disc2.itemData(i) == p.get("discount_level2"):
                    self.f_disc2.setCurrentIndex(i); break
        # Show stock section with current level (only for non-case products)
        stock = p.get("stock", 0)
        self.stock_current_lbl.setText(f"Current stock: {stock} unit{'s' if stock != 1 else ''}")
        self.stock_qty.setValue(1)
        self.stock_reason.setCurrentIndex(0)
        # Stock section is hidden for case products — they use "Restock via Case" instead
        self.stock_section.setVisible(not p["is_case"])

    def _save_product(self):
        barcode = self.f_barcode[1].text().strip()
        name    = self.f_name[1].text().strip()
        if not barcode or not name:
            QMessageBox.warning(self, "Missing Fields", "Barcode and Name are required."); return
        try:    cost = float(self.f_cost[1].text() or 0)
        except: QMessageBox.warning(self, "Invalid Cost", "Enter a valid cost."); return
        group_id         = self.f_group.currentData()
        alias_group_id   = self.f_alias_group.selected_id()
        variant_group_id = self.f_variant_group.selected_id()

        is_case         = self.t_case.isChecked()
        is_pool_mode    = is_case and self.case_mode_pool.isChecked()
        case_group_id   = self.f_case_group_combo.currentData() if is_pool_mode else None
        case_product_id = self.f_case_parent.selected_id() if (is_case and not is_pool_mode) else None
        # Each mode uses its own case_qty spinbox
        if is_case:
            case_qty = self.f_case_qty2.value() if is_pool_mode else self.f_case_qty.value()
        else:
            case_qty = None

        # Mode 1 — derive cost from linked parent single product
        if is_case and case_product_id:
            parent = get_product_by_id(case_product_id)
            if parent and parent["cost"] > 0:
                cost = round(parent["cost"] * (case_qty or 1), 4)
                self.f_cost[1].setText(str(cost))

        # Mode 2 — derive cost + price from the case group row
        if is_pool_mode and case_group_id:
            g = get_case_group_by_id(case_group_id)
            if g:
                cost          = g["cost"]
                selling_price = g["selling_price"]
                self.f_cost[1].setText(str(cost))
            else:
                selling_price = self._get_selling_price(cost, group_id)
        else:
            selling_price = self._get_selling_price(cost, group_id)

        # Mode 1 linked cases use case_profit_pct instead of group margin
        if is_case and case_product_id and not is_pool_mode:
            from core.db_config import get as cfg_get
            try:
                pct = float(cfg_get("case_profit_pct", "0.10"))
            except (ValueError, TypeError):
                pct = 0.10
            selling_price = round(cost * (1 + pct), 2)

        disc1_id = self.f_disc1.currentData()
        disc2_id = self.f_disc2.currentData()
        if disc1_id == "custom": disc1_id = None
        if disc2_id == "custom": disc2_id = None

        kwargs = dict(
            barcode=barcode, name=name,
            cost=cost, selling_price=selling_price,
            group_id=group_id,
            alias_group_id=alias_group_id,
            variant_group_id=variant_group_id,
            gct_applicable=int(self.t_gct.isChecked()),
            is_case=int(is_case),
            case_qty=case_qty,
            case_product_id=case_product_id,
            case_group_id=case_group_id,
            discount_level1=disc1_id,
            discount_level2=disc2_id,
        )
        # Custom (inline) discount tiers override the discount_level FK above
        if self.f_disc1.currentData() == "custom":
            kwargs["inline_disc1_qty"] = self.f_disc1_qty.value()
            kwargs["inline_disc1_pct"] = self.f_disc1_pct.value()
        elif self.f_disc1.currentData() is not None:
            kwargs["inline_disc1_qty"] = None
            kwargs["inline_disc1_pct"] = None
        if self.f_disc2.currentData() == "custom":
            kwargs["inline_disc2_qty"] = self.f_disc2_qty.value()
            kwargs["inline_disc2_pct"] = self.f_disc2_pct.value()
        elif self.f_disc2.currentData() is not None:
            kwargs["inline_disc2_qty"] = None
            kwargs["inline_disc2_pct"] = None
        try:
            if self._editing_product_id:
                old = get_product_by_id(self._editing_product_id)
                price_changed = old and round(old["selling_price"], 2) != round(selling_price, 2)
                cost_changed  = old and round(old["cost"], 4) != round(cost, 4)
                update_product(self._editing_product_id, **kwargs)
                # Sync all group members if cost or price changed
                if (price_changed or cost_changed) and (alias_group_id or variant_group_id):
                    self._sync_group_members(
                        cost, selling_price, alias_group_id, variant_group_id
                    )
                # Cascade cost change to linked case products
                if cost_changed and not is_case:
                    n = cascade_single_cost_to_cases(self._editing_product_id)
                    if n:
                        QMessageBox.information(
                            self, "Case Prices Updated",
                            f"Cost change cascaded to {n} linked case product{'s' if n != 1 else ''}.\n"
                            f"Case selling prices have been recalculated."
                        )
                QMessageBox.information(self, "Saved", f"'{name}' updated.")
            else:
                add_product(**kwargs)
                QMessageBox.information(self, "Added", f"'{name}' added.")
                self._new_product_form()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        self._load_products(self.product_search.text())

    def _sync_group_members(self, cost: float, selling_price: float,
                            alias_group_id: int | None,
                            variant_group_id: int | None):
        """Silently sync cost and selling_price to all members of each group.

        Alias and variant groups are defined as always having the same cost
        and selling price — no confirmation needed, just apply immediately.
        """
        group_ids = [g for g in (alias_group_id, variant_group_id) if g]
        if not group_ids:
            return

        updated = []
        for gid in group_ids:
            members = [
                p for p in get_products(limit=5000)
                if (p.get("alias_group_id") == gid or p.get("variant_group_id") == gid)
                and p["id"] != self._editing_product_id
            ]
            for p in members:
                update_product(p["id"], cost=cost, selling_price=selling_price)
                updated.append(p["name"])
            update_price_group(gid, selling_price=selling_price)

        if updated:
            names = ", ".join(updated)
            QMessageBox.information(
                self, "Group Synced",
                f"Cost (${cost:.4f}) and price (${selling_price:.2f}) synced to:\n{names}"
            )

    def _delete_product(self, pid: int):
        p = get_product_by_id(pid)
        if not p: return
        reply = QMessageBox.question(self, "Delete", f"Delete '{p['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_product(pid); self._load_products(self.product_search.text())

    def _stock_add(self):
        if not self._editing_product_id: return
        qty    = self.stock_qty.value()
        reason = self.stock_reason.currentText()
        adjust_stock(self._editing_product_id, qty, reason, self.user["id"])
        p = get_product_by_id(self._editing_product_id)
        stock = p["stock"] if p else 0
        self.stock_current_lbl.setText(f"Current stock: {stock} unit{'s' if stock != 1 else ''}")
        self.stock_qty.setValue(1)

    def _stock_remove(self):
        if not self._editing_product_id: return
        qty    = self.stock_qty.value()
        reason = self.stock_reason.currentText()
        adjust_stock(self._editing_product_id, -qty, reason, self.user["id"])
        p = get_product_by_id(self._editing_product_id)
        stock = p["stock"] if p else 0
        self.stock_current_lbl.setText(f"Current stock: {stock} unit{'s' if stock != 1 else ''}")
        self.stock_qty.setValue(1)

    def _calc_selling_price(self):
        try:    cost = float(self.f_cost[1].text() or 0)
        except: return
        gid = self.f_group.currentData()
        price = self._get_selling_price(cost, gid)
        self.f_price.setText(f"${price:.2f}")
        m = self._group_markup(gid)
        self.f_price_hint.setText(f"= ${cost:.2f} × (1 + {m*100:.0f}%) = ${price:.2f}" if m and cost else "")

    def _get_selling_price(self, cost, group_id):
        m = self._group_markup(group_id)
        return round(cost * (1 + m), 2) if m and cost else cost

    def _group_markup(self, group_id) -> float:
        if not group_id: return 0.0
        try:
            import sqlite3; from config import DB_PRODUCTS
            con = sqlite3.connect(DB_PRODUCTS)
            row = con.execute("SELECT profit_margin FROM groups WHERE id=?", (group_id,)).fetchone()
            con.close(); return float(row[0]) if row and row[0] else 0.0
        except: return 0.0

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

    def _on_case_toggled(self, state):
        self.case_box.setVisible(bool(state))
        if bool(state):
            self.f_case_parent.exclude_id(self._editing_product_id)
            self.stock_section.setVisible(False)
            self._populate_case_group_combo()
            self._on_case_mode_changed()
        else:
            self.f_case_parent.clear_value()
            self.f_case_cost_hint.setText("")
            self.f_group.setEnabled(True)
            self.f_group.setToolTip("")
            self.stock_section.setVisible(bool(self._editing_product_id))

    def _on_case_mode_changed(self):
        """Switch between Mode 1 (linked) and Mode 2 (shared pool) panels."""
        linked = self.case_mode_linked.isChecked()
        self.case_mode1_frame.setVisible(linked)
        self.case_mode2_frame.setVisible(not linked)
        if linked:
            self._on_case_parent_changed()
        else:
            self._on_case_group_changed()

    # ── Mode 1 helpers ────────────────────────────────────────────────────────

    def _populate_case_parents(self, select_id: int = None):
        """Restore a saved parent selection when editing."""
        self.f_case_parent.exclude_id(self._editing_product_id)
        self.f_case_parent.set_value(select_id)
        self._on_case_parent_changed()

    def _on_case_parent_changed(self):
        """Update cost hint and inherit group from parent when a parent is selected."""
        parent_id = self.f_case_parent.selected_id()
        qty = self.f_case_qty.value()
        if parent_id is None:
            self.f_case_cost_hint.setText("Cost will be set manually from the Cost field above.")
            self.f_group.setEnabled(True)
            self.f_group.setToolTip("")
        else:
            parent = get_product_by_id(parent_id)
            if parent:
                derived = parent["cost"] * qty
                self.f_case_cost_hint.setText(
                    f"Cost = ${parent['cost']:.4f} × {qty} = ${derived:.4f}  "
                    f"(auto-set on save)"
                )
                parent_group = parent.get("group_id")
                for i in range(self.f_group.count()):
                    if self.f_group.itemData(i) == parent_group:
                        self.f_group.setCurrentIndex(i); break
                self.f_group.setEnabled(False)
                self.f_group.setToolTip(
                    "Group is inherited from the parent single product.\n"
                    "Change the parent to change the group."
                )
            else:
                self.f_case_cost_hint.setText("")
        self._refresh_case_stock_lbl()

    def _refresh_case_stock_lbl(self):
        parent_id = self.f_case_parent.selected_id()
        qty = self.f_case_qty.value() or 1
        if not parent_id:
            self.case_stock_lbl.setText("Select a parent product to see stock.")
            self.case_restock_add_btn.setEnabled(False)
            self.case_restock_remove_btn.setEnabled(False)
            return
        parent = get_product_by_id(parent_id)
        stock = parent["stock"] if parent else 0
        cases_avail = stock // qty
        remainder   = stock % qty
        txt = (f"Parent stock: {stock} unit{'s' if stock != 1 else ''}  →  "
               f"~{cases_avail} case{'s' if cases_avail != 1 else ''} available")
        if remainder:
            txt += f"  (+{remainder} loose unit{'s' if remainder != 1 else ''})"
        self.case_stock_lbl.setText(txt)
        self.case_restock_add_btn.setEnabled(True)
        self.case_restock_remove_btn.setEnabled(True)
        self.case_restock_feedback.setText("")

    def _case_restock_add(self):
        parent_id = self.f_case_parent.selected_id()
        if not parent_id: return
        cases = self.case_restock_qty.value()
        units = cases * (self.f_case_qty.value() or 1)
        adjust_stock(parent_id, units, "Restock (case)", self.user["id"])
        self._refresh_case_stock_lbl()
        self.case_restock_feedback.setStyleSheet(f"color:{GREEN};font-size:10px;font-weight:600;")
        self.case_restock_feedback.setText(
            f"✓  Added {cases} case{'s' if cases != 1 else ''} ({units} units) to parent stock.")

    def _case_restock_remove(self):
        parent_id = self.f_case_parent.selected_id()
        if not parent_id: return
        cases = self.case_restock_qty.value()
        units = cases * (self.f_case_qty.value() or 1)
        adjust_stock(parent_id, -units, "Correction (case)", self.user["id"])
        self._refresh_case_stock_lbl()
        self.case_restock_feedback.setStyleSheet(f"color:{AMBER_DARK};font-size:10px;font-weight:600;")
        self.case_restock_feedback.setText(
            f"✓  Removed {cases} case{'s' if cases != 1 else ''} ({units} units) from parent stock.")

    # ── Mode 2 helpers ────────────────────────────────────────────────────────

    def _populate_case_group_combo(self, select_id: int = None):
        self.f_case_group_combo.blockSignals(True)
        self.f_case_group_combo.clear()
        self.f_case_group_combo.addItem("— Select case group —", None)
        for g in get_case_groups():
            self.f_case_group_combo.addItem(g["name"], g["id"])
            if g["id"] == select_id:
                self.f_case_group_combo.setCurrentIndex(self.f_case_group_combo.count() - 1)
        self.f_case_group_combo.blockSignals(False)
        self._on_case_group_changed()

    def _on_case_group_changed(self):
        gid = self.f_case_group_combo.currentData()
        if not gid:
            self.case_grp_info_lbl.setText("")
            self.pool_stock_lbl.setText("Select a case group to see pool stock.")
            self.pool_restock_add_btn.setEnabled(False)
            self.pool_restock_remove_btn.setEnabled(False)
            return
        g = get_case_group_by_id(gid)
        if not g: return
        self.case_grp_info_lbl.setText(
            f"Cost: ${g['cost']:.4f}   Selling price: ${g['selling_price']:.2f}"
            f"   Case qty: {g['case_qty'] or '—'}"
        )
        pool = g["pool_stock"]
        self.pool_stock_lbl.setText(
            f"Pool stock: {pool} case{'s' if pool != 1 else ''} available")
        self.pool_restock_add_btn.setEnabled(True)
        self.pool_restock_remove_btn.setEnabled(True)
        self.pool_restock_feedback.setText("")

    def _create_case_group(self):
        """Inline dialog to create a new case group."""
        dlg = QDialog(self); dlg.setWindowTitle("New Case Group")
        dlg.setMinimumWidth(320)
        lay = QVBoxLayout(dlg); lay.setSpacing(10); lay.setContentsMargins(16,16,16,16)
        lay.addWidget(QLabel("Group Name"))
        name_edit = QLineEdit(); name_edit.setPlaceholderText("e.g. SPRITE 330ML CASES")
        name_edit.setStyleSheet(self._input_style()); name_edit.setFixedHeight(34)
        lay.addWidget(name_edit)
        lay.addWidget(QLabel("Units per Case"))
        qty_spin = QSpinBox(); qty_spin.setMinimum(1); qty_spin.setMaximum(9999); qty_spin.setValue(24)
        qty_spin.setStyleSheet(self._input_style()); qty_spin.setFixedHeight(34)
        lay.addWidget(qty_spin)
        lay.addWidget(QLabel("Cost per Case ($)"))
        cost_edit = QLineEdit("0.00"); cost_edit.setStyleSheet(self._input_style()); cost_edit.setFixedHeight(34)
        lay.addWidget(cost_edit)
        lay.addWidget(QLabel("Selling Price per Case ($)"))
        price_edit = QLineEdit("0.00"); price_edit.setStyleSheet(self._input_style()); price_edit.setFixedHeight(34)
        lay.addWidget(price_edit)
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(dlg.reject)
        save_btn   = QPushButton("Create"); save_btn.clicked.connect(dlg.accept)
        save_btn.setStyleSheet(self._accent_btn())
        btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        name = name_edit.text().strip().upper()
        if not name:
            QMessageBox.warning(self, "Required", "Group name is required."); return
        try:
            cost  = float(cost_edit.text() or 0)
            price = float(price_edit.text() or 0)
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Enter valid cost and price values."); return

        # Check for duplicate name before inserting
        existing = [g for g in get_case_groups() if g["name"] == name]
        if existing:
            QMessageBox.warning(
                self, "Name Already Exists",
                f'A case group named "{name}" already exists.\n'
                f'Please choose a different name or select the existing group.'
            )
            return

        try:
            new_id = add_case_group(name, qty_spin.value(), cost, price)
        except Exception as e:
            QMessageBox.critical(self, "Error Creating Group", str(e))
            return
        self._populate_case_group_combo(select_id=new_id)

    def _pool_restock_add(self):
        gid = self.f_case_group_combo.currentData()
        if not gid: return
        cases = self.pool_restock_qty.value()
        adjust_case_group_stock(gid, cases, "Restock", self.user["id"])
        self._on_case_group_changed()
        self.pool_restock_feedback.setStyleSheet(f"color:{GREEN};font-size:10px;font-weight:600;")
        self.pool_restock_feedback.setText(
            f"✓  Added {cases} case{'s' if cases != 1 else ''} to pool.")

    def _pool_restock_remove(self):
        gid = self.f_case_group_combo.currentData()
        if not gid: return
        cases = self.pool_restock_qty.value()
        adjust_case_group_stock(gid, -cases, "Correction", self.user["id"])
        self._on_case_group_changed()
        self.pool_restock_feedback.setStyleSheet(f"color:{AMBER_DARK};font-size:10px;font-weight:600;")
        self.pool_restock_feedback.setText(
            f"✓  Removed {cases} case{'s' if cases != 1 else ''} from pool.")

    def _populate_groups(self):
        self.f_group.clear(); self.f_group.addItem("— No Group —", None)
        for g in get_groups(): self.f_group.addItem(g["name"], g["id"])

    def _build_custom_disc_inputs(self, tier: str):
        """Build inline qty + pct inputs for a custom discount tier."""
        from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox as _QSpinBox
        from PyQt6.QtWidgets import QFrame as _QFrame
        frame = _QFrame()
        frame.setStyleSheet(
            f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};"
            f"border-radius:6px;"
        )
        from PyQt6.QtWidgets import QHBoxLayout as _QHL
        _spinbox_css = (
            f"QSpinBox,QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:7px;"
            f"padding:0 8px;font-size:12px;}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{AMBER};}}"
        )
        fl = _QHL(frame); fl.setContentsMargins(8, 6, 8, 6); fl.setSpacing(8)
        fl.addWidget(self._flabel("Min Qty:"))
        qty = _QSpinBox(); qty.setMinimum(1); qty.setMaximum(9999)
        qty.setFixedHeight(30); qty.setFixedWidth(70)
        qty.setStyleSheet(_spinbox_css)
        fl.addWidget(qty)
        fl.addWidget(self._flabel("Discount %:"))
        pct = QDoubleSpinBox(); pct.setMinimum(0.1); pct.setMaximum(99.9)
        pct.setDecimals(1); pct.setSuffix("%")
        pct.setFixedHeight(30); pct.setFixedWidth(80)
        pct.setStyleSheet(_spinbox_css)
        fl.addWidget(pct); fl.addStretch()
        setattr(self, f"f_disc{tier}_qty", qty)
        setattr(self, f"f_disc{tier}_pct", pct)
        return frame

    def _populate_discount_levels(self, combo):
        combo.clear(); combo.addItem("— None —", None)
        try:
            from core.db_products import get_discount_levels
            for lvl in get_discount_levels():
                combo.addItem(
                    f"{lvl['name']}  ({lvl['discount_percent']}% off, min qty {lvl['min_quantity']})",
                    lvl["id"]
                )
        except Exception:
            pass
        combo.addItem("Custom…", "custom")


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
            sales = QTableWidgetItem(f"${live_sales:.2f}  ({txns} txns)")
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
            self.rpt_cards["total_sales"].setText(f"${session['_sales']:.2f}")
            self.rpt_cards["total_gct"].setText(f"${session['_gct']:.2f}")
            self.rpt_cards["transactions"].setText(str(session["_txns"]))
            self.rpt_cards["discounts"].setText(f"${session['_disc']:.2f}")

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
            tot = QTableWidgetItem(f"${r['total']:.2f}"); tot.setForeground(QColor(AMBER)); tot.setTextAlignment(R)
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
            pi = QTableWidgetItem(f"${it['unit_price']:.2f}"); pi.setTextAlignment(R); self.tx_items_table.setItem(r, 2, pi)
            ti = QTableWidgetItem(f"${it['line_total']:.2f}"); ti.setForeground(QColor(GREEN)); ti.setTextAlignment(R); self.tx_items_table.setItem(r, 3, ti)
        self.tx_footer.setText(f"Subtotal: ${receipt['subtotal']:.2f}  |  GCT: ${receipt['gct_amount']:.2f}  |  <b>Total: ${receipt['total']:.2f}</b>")
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
        self.vr_items_table.setHorizontalHeaderLabels(["✓","Item","Qty","Price","Total"])
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
            tot = QTableWidgetItem(f"${r['total']:.2f}"); tot.setForeground(QColor(AMBER)); tot.setTextAlignment(R); self.vr_table.setItem(i, 4, tot)
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
        for r, it in enumerate(self._vr_items_data):
            chk_w = QWidget(); chk_l = QHBoxLayout(chk_w); chk_l.setContentsMargins(4,0,4,0); chk_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox(); chk.setChecked(True); chk.setEnabled(is_partial); chk.stateChanged.connect(self._vr_update_selected_amount)
            chk_l.addWidget(chk); self.vr_items_table.setCellWidget(r, 0, chk_w)
            self.vr_items_table.setItem(r, 1, QTableWidgetItem(it["product_name"]))
            qi = QTableWidgetItem(str(it["quantity"])); qi.setTextAlignment(Qt.AlignmentFlag.AlignCenter); self.vr_items_table.setItem(r, 2, qi)
            pi = QTableWidgetItem(f"${it['unit_price']:.2f}"); pi.setTextAlignment(R); self.vr_items_table.setItem(r, 3, pi)
            ti = QTableWidgetItem(f"${it['line_total']:.2f}"); ti.setForeground(QColor(GREEN)); ti.setTextAlignment(R); self.vr_items_table.setItem(r, 4, ti)
        self.vr_totals.setText(f"Subtotal: ${receipt['subtotal']:.2f}  |  GCT: ${receipt['gct_amount']:.2f}  |  <b>Total: ${receipt['total']:.2f}</b>")
        self.vr_totals.setTextFormat(Qt.TextFormat.RichText)
        self.vr_status_banner.setVisible(False); self.vr_reason.clear(); self._vr_update_buttons()

    def _vr_on_mode_changed(self):
        is_partial = self.vr_refund_mode.currentIndex()==1
        for r in range(self.vr_items_table.rowCount()):
            w = self.vr_items_table.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk: chk.setEnabled(is_partial)
        self._vr_update_selected_amount()

    def _vr_update_selected_amount(self):
        if not self._vr_items_data or self.vr_refund_mode.currentIndex() == 0:
            self.vr_amount_lbl.setText(""); return
        total = 0.0
        for r, it in enumerate(self._vr_items_data):
            w = self.vr_items_table.cellWidget(r, 0)
            chk = w.findChild(QCheckBox) if w else None
            if chk and chk.isChecked():
                total += it["line_total"]
        self.vr_amount_lbl.setText(f"Selected refund: ${total:.2f}")

    def _vr_update_buttons(self):
        ok = self._vr_selected_tx_id is not None and self._vr_selected_tx_status=="completed" and bool(self.vr_reason.text().strip())
        self.vr_void_btn.setEnabled(ok); self.vr_refund_btn.setEnabled(ok)

    def _vr_do_void(self):
        reason = self.vr_reason.text().strip()
        if not reason: QMessageBox.warning(self, "Reason Required", "Please enter a reason."); return
        reply = QMessageBox.question(self, "Confirm Void", f"Void receipt #{self._vr_selected_tx_id}?\nReason: {reason}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        if void_receipt(self._vr_selected_tx_id, self.user["id"], reason):
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
        for r, it in enumerate(self._vr_items_data):
            w = self.vr_items_table.cellWidget(r, 0)
            chk = w.findChild(QCheckBox) if w else None
            if not is_partial or (chk and chk.isChecked()): items.append(it)
        if not items: QMessageBox.warning(self, "No Items", "Select at least one item."); return
        amount = sum(it["line_total"] for it in items)
        mode = "Partial" if is_partial else "Full"
        reply = QMessageBox.question(self, f"Confirm {mode} Refund", f"{mode} refund — ${amount:.2f}\nReason: {reason}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        rtype = "partial" if is_partial else "full"
        if refund_receipt(self._vr_selected_tx_id, self.user["id"], reason, amount, rtype):
            # Increment stock for refunded items
            from core.db_config import get_bool
            if get_bool("stock_tracking", False):
                from core.db_products import increment_stock
                for it in items:
                    if it.get("product_id"):
                        increment_stock(it["product_id"], it["quantity"])
            # Print refund receipt
            receipt = get_receipt_by_id(self._vr_selected_tx_id)
            if receipt:
                from core.db_checkout import get_refunds_for_receipt
                refunds = get_refunds_for_receipt(receipt["id"])
                refund_rec = refunds[0] if refunds else {"reason": reason, "amount": amount, "refund_type": rtype}
                from utils.print_manager import print_refund
                print_refund(receipt, refund_rec, refunded_by_user=self.user, parent=self)
            self.vr_void_btn.setEnabled(False); self.vr_refund_btn.setEnabled(False)
            self.vr_status_banner.setText(f"✓  {mode} refund of ${amount:.2f} issued."); self.vr_status_banner.setStyleSheet(f"color:{AMBER};font-size:12px;font-weight:600;"); self.vr_status_banner.setVisible(True)
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
            inp.setText(f"{k['product_name']} (${k['product_price']:.2f})" if k.get("product_name") else "")
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
            if pid:
                p = get_product_by_id(pid)
                assignments.append({"slot":slot,"product_id":pid,"product_name":p["name"] if p else text,"product_price":p["selling_price"] if p else 0})
            else:
                assignments.append({"slot":slot,"product_id":None,"product_name":None,"product_price":None})
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
            f"border-radius:7px;padding:0 10px;font-size:12px;font-weight:400;}}"
            f"QLineEdit:focus{{border-color:{AMBER};background:#fffef9;}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
            f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {b};"
            f"border-radius:7px;padding:0 8px;font-size:12px;}}"
            f"QSpinBox:focus{{border-color:{AMBER};}}"
        )

    def _combo_style(self):
        return (
            f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;font-weight:400;}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
            f"QComboBox::down-arrow{{width:10px;height:10px;}}"
            f"QComboBox QAbstractItemView{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};outline:none;"
            f"selection-background-color:{AMBER};selection-color:white;}}"
        )

    def _accent_btn(self):
        return f"QPushButton{{background:{AMBER};color:white;border:none;border-radius:17px;font-size:12px;font-weight:600;padding:0 16px;}}QPushButton:hover{{background:{AMBER_DARK};}}"

    def _outline_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:transparent;color:{LABEL_TEXT};border:1.5px solid {BORDER};border-radius:16px;font-size:11px;font-weight:600;padding:0 14px;}}QPushButton:hover{{background:{WARM_WHITE};color:{DARK_CARD};}}QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}")
        return b

    def _danger_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:{RED_LIGHT};color:{RED};border:none;border-radius:16px;font-size:11px;font-weight:600;padding:0 14px;}}QPushButton:hover{{background:{RED};color:white;}}QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};}}")
        return b

    def _success_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:{GREEN_LIGHT};color:{GREEN};border:none;border-radius:16px;font-size:11px;font-weight:600;padding:0 14px;}}QPushButton:hover{{background:{GREEN};color:white;}}QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};}}")
        return b

    def _icon_btn(self, icon, tooltip=""):
        b = QPushButton(icon); b.setFixedSize(34,34); b.setToolTip(tooltip); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:{WARM_WHITE};color:{DARK_CARD};border:1.5px solid {BORDER};border-radius:7px;font-size:14px;font-weight:700;}}QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}")
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
