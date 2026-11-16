"""
ui/manager/manager_window.py
Manager dashboard — inherits SupervisorWindow and prepends manager-only tabs:
  • Users     — add / edit / delete users, role assignment
  • Setup / Inventory / Data settings pages — one page per topic (see ui/shared/tab_registry.py)
  • Quick Keys — (inherited from supervisor, shown here too)
  • All supervisor tabs (Products, Reports, Transactions, Void/Refund)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QCheckBox, QAbstractItemView,
    QMessageBox, QScrollArea, QSplitter, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QFormLayout, QDialog, QSizePolicy,
)
from PyQt6.QtCore  import Qt, pyqtSignal
from PyQt6.QtGui   import QColor, QDoubleValidator

from ui.supervisor.supervisor_window import SupervisorWindow
from utils.currency import format_currency
from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_4, DARK_CARD,
    WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN, GREEN_LIGHT, BLUE,
)
from core.db_users    import get_users
from ui.manager.user_dialog import UserDialog
from core.db_config   import (
    get_business, update_business, get, set as cfg_set, set_many,
    clean_lines, BUSINESS_TEXT_MAX,
    gct_rate, get_pg_config, save_pg_config, get_quick_keys, save_quick_keys,
)
from core.db_products import get_products, get_product_by_id, get_groups, add_group, delete_group, update_group_margin, recalculate_all_cases
from ui.shared.checkbox import make_checkbox
from ui.shared.upper_text import make_upper_textbox

# AMBER (#EF9F27) used directly as text on white measured ~2.2:1 — same
# failure pattern found and fixed throughout the cashier section. Scoped
# locally rather than changing the shared AMBER constant, which is used
# correctly elsewhere in this file as a background/accent color.
AMBER_TEXT_ON_WHITE = "#8a5510"


# ================================================================
# MANAGER WINDOW
# ================================================================

from core.db_config import checkout_quick_amounts


class ManagerWindow(SupervisorWindow):
    """
    Extends SupervisorWindow.
    Supervisor tabs are inherited.  Manager-only tabs are prepended.
    """
    logout_requested = pyqtSignal()

    def __init__(self, user: dict, parent=None):
        # We call BaseWindow.__init__ directly to skip SupervisorWindow._build_ui
        from ui.base_window import BaseWindow
        BaseWindow.__init__(self, parent)
        self.user = user
        self._editing_product_id = None
        self.setWindowTitle("POS System — Manager")
        self.setMinimumSize(1280, 720)
        self._build_manager_ui()
        self._start_clock()

    def _build_manager_ui(self):
        root = QWidget(); root.setStyleSheet(f"background:{WARM_WHITE};")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_manager_tabs(), stretch=1)

    def _build_topbar(self):
        bar = QFrame(); bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{DARK};border-bottom:1px solid {DARK_4};")
        lay = QHBoxLayout(bar); lay.setContentsMargins(16,0,16,0)
        left = QLabel(f"POS System  |  Manager:  {self.user['full_name']}")
        left.setStyleSheet("color:white;font-size:13px;font-weight:600;")
        self._clock = QLabel(); self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # MUTED (#6B6860) on the near-black topbar measured ~3.5:1 — under
        # the 4.5:1 floor. Same failure already found and fixed in
        # supervisor_window.py's/cashier_window.py's topbar clocks.
        self._clock.setStyleSheet("color:#9a9690;font-size:11px;font-family:'DM Mono',monospace;")
        drawer_btn = QPushButton("🔓  Open Drawer"); drawer_btn.setFixedHeight(30)
        drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        drawer_btn.setStyleSheet(f"""
            QPushButton{{background:transparent;color:{AMBER};
            border:1px solid {AMBER};border-radius:15px;font-size:11px;
            font-weight:600;padding:0 14px;}}
            QPushButton:hover{{background:{AMBER};color:{DARK};}}
        """)
        drawer_btn.clicked.connect(self._open_drawer_manual)

        logout = QPushButton("Logout  ↗"); logout.setFixedHeight(30)
        logout.setCursor(Qt.CursorShape.PointingHandCursor)
        # White text on amber measured ~2.2:1 — same failure pattern
        # found throughout the app. Dark text clears ~8.9:1.
        logout.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:{DARK};border:none;
            border-radius:15px;font-size:11px;font-weight:700;padding:0 16px;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        logout.clicked.connect(self._handle_logout)
        lay.addWidget(left); lay.addStretch(); lay.addWidget(self._clock); lay.addStretch()
        lay.addWidget(drawer_btn); lay.addSpacing(10); lay.addWidget(logout)
        return bar

    def _open_drawer_manual(self):
        """Open Drawer button — a no-sale drawer open, always supervisor/
        manager authorised (independent of print mode — see
        utils.thermal_printer.ThermalPrinter.kick_drawer)."""
        from ui.shared.drawer_auth_dialog import DrawerAuthDialog
        dlg = DrawerAuthDialog(parent=self)
        if dlg.exec():
            from utils.print_manager import open_drawer_manual
            open_drawer_manual(dlg.authorized_user, parent=self)

    def _build_manager_tabs(self):
        # Same areas as the supervisor, plus the manager-only pages
        # (see ui/shared/tab_registry.py).
        from ui.shared.tab_registry import build_role_tabs
        return build_role_tabs(self, "manager")

    def _build_backup_tab(self):
        from ui.manager.backup_tab import BackupTab
        return BackupTab(self.user)

    def _on_logout_confirmed(self):
        """Manager logout: start a background backup if switched on."""
        try:
            from core import backup as bk
            if bk.load_settings()["on_manager_logout"]:
                bk.run_async("logout")
        except Exception:
            pass                       # a backup problem must never block logging out

    def _build_receipt_tab(self):
        from ui.manager.receipt_tab import ReceiptDesignerTab
        tab = ReceiptDesignerTab(self)
        return tab

    def _build_pickup_tab(self):
        from ui.manager.pickup_tab import PickupTab
        return PickupTab(self)

    def _usr_refresh_on_show(self):
        """Reload users (another manager may have added/changed accounts) and
        re-apply the search/role filter the manager had typed."""
        self._usr_load()
        self._usr_filter()

    # ================================================================
    # USERS TAB
    # ================================================================

    def _build_users_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)

        # User list
        card = QFrame()
        card.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        cl = QVBoxLayout(card); cl.setContentsMargins(10,10,10,10); cl.setSpacing(8)

        tb = QHBoxLayout(); tb.setSpacing(8)
        self.usr_search = QLineEdit()
        self.usr_search.setPlaceholderText("🔍  Search users…")
        self.usr_search.setFixedHeight(34); self.usr_search.setStyleSheet(self._input_style())
        self.usr_search.textChanged.connect(self._usr_filter)

        self.usr_role_filter = QComboBox()
        self.usr_role_filter.addItems(["All Roles","cashier","supervisor","manager"])
        self.usr_role_filter.setFixedHeight(34); self.usr_role_filter.setStyleSheet(self._combo_style())
        self.usr_role_filter.currentIndexChanged.connect(self._usr_filter)

        add_btn = QPushButton("+ Add User"); add_btn.setFixedHeight(34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(self._accent_btn()); add_btn.clicked.connect(self._usr_open_add)

        tb.addWidget(self.usr_search, stretch=1)
        tb.addWidget(self.usr_role_filter); tb.addWidget(add_btn)
        cl.addLayout(tb)

        self.usr_table = QTableWidget(); self.usr_table.setColumnCount(5)
        self.usr_table.setHorizontalHeaderLabels(["Name","Username","Role","Status","Actions"])
        hh = self.usr_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in [1,2,3,4]: hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.usr_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.usr_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.usr_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.usr_table.verticalHeader().setVisible(False)
        self.usr_table.setShowGrid(False)
        self.usr_table.setStyleSheet(self._table_style())
        self.usr_table.cellDoubleClicked.connect(self._usr_on_row_double_clicked)
        cl.addWidget(self.usr_table, stretch=1)

        lay.addWidget(card, stretch=1)
        self._usr_all_users = []
        self._usr_load(); return w

    def _usr_load(self):
        self._usr_all_users = get_users()
        self._usr_populate(self._usr_all_users)

    def _usr_populate(self, users):
        self.usr_table.setRowCount(0)
        role_colors = {"cashier":BLUE,"supervisor":AMBER_TEXT_ON_WHITE,"manager":RED}
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        for u in users:
            row = self.usr_table.rowCount(); self.usr_table.insertRow(row)
            self.usr_table.setRowHeight(row, 36)
            name = QTableWidgetItem(u["full_name"]); name.setData(Qt.ItemDataRole.UserRole, u["id"])
            name.setForeground(QColor(DARK_CARD))
            user = QTableWidgetItem(u["username"]); user.setForeground(QColor(MUTED))
            role = QTableWidgetItem(u["role"].capitalize())
            role.setForeground(QColor(role_colors.get(u["role"],MUTED))); role.setTextAlignment(C)
            stat = QTableWidgetItem("Active" if u["is_active"] else "Inactive")
            stat.setForeground(QColor(GREEN if u["is_active"] else RED)); stat.setTextAlignment(C)
            edit = QPushButton("Edit"); edit.setFixedHeight(26)
            edit.setCursor(Qt.CursorShape.PointingHandCursor)
            edit.setStyleSheet(f"QPushButton{{background:transparent;color:{AMBER_TEXT_ON_WHITE};border:1px solid {AMBER};border-radius:5px;font-size:11px;}}QPushButton:hover{{background:{AMBER};color:{DARK};}}")
            edit.clicked.connect(lambda _, uid=u["id"]: self._usr_open_edit(uid))
            cell = QWidget(); cl = QHBoxLayout(cell); cl.setContentsMargins(4,2,4,2); cl.addWidget(edit)
            for col, item in enumerate([name,user,role,stat]):
                self.usr_table.setItem(row, col, item)
            self.usr_table.setCellWidget(row, 4, cell)

    def _usr_filter(self):
        q    = self.usr_search.text().lower()
        role = self.usr_role_filter.currentText().lower()
        f = [u for u in self._usr_all_users
             if (q in u["full_name"].lower() or q in u["username"].lower())
             and (role == "all roles" or u["role"] == role)]
        self._usr_populate(f)

    def _usr_on_row_double_clicked(self, row, _col):
        item = self.usr_table.item(row, 0)
        if item: self._usr_open_edit(item.data(Qt.ItemDataRole.UserRole))

    def _usr_open_add(self):
        dlg = UserDialog(self, current_user_id=self.user["id"])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._usr_load()

    def _usr_open_edit(self, uid):
        u = next((u for u in self._usr_all_users if u["id"]==uid), None)
        if not u: return
        dlg = UserDialog(self, current_user_id=self.user["id"], editing=u)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._usr_load()
        self.usr_table.clearSelection()

    # ================================================================
    # BUSINESS TAB
    # ================================================================

    # ================================================================
    # SETTINGS PAGES  (Setup / Inventory / Data areas)
    # Each page has its own Save button and its own unsaved-changes check.
    # ================================================================

    def _settings_page(self, title):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(fw); lay.setContentsMargins(20,20,20,20); lay.setSpacing(14)
        lay.addWidget(self._section_lbl(title))
        lay.addWidget(self._hdiv())
        return scroll, fw, lay

    def _settings_footer(self, scroll, fw, lay, feedback_attr, save_text, slot):
        lay.addStretch()
        fb = QLabel("")
        fb.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        fb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        setattr(self, feedback_attr, fb)
        lay.addWidget(fb)
        btn = QPushButton(save_text); btn.setFixedHeight(38)
        btn.setStyleSheet(self._accent_btn()); btn.clicked.connect(slot)
        lay.addWidget(btn)
        scroll.setWidget(fw)
        return scroll

    def _flash(self, feedback_attr, text, ok=True):
        lbl = getattr(self, feedback_attr)
        lbl.setStyleSheet(f"color:{GREEN if ok else RED};font-size:11px;font-weight:600;")
        lbl.setText(text)

    def _hinted(self, widget, text):
        box = QVBoxLayout(); box.setSpacing(3)
        box.addWidget(widget); box.addWidget(self._fhint(text))
        return box

    def _spin_style(self, kind="QDoubleSpinBox"):
        return (f"{kind}{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:7px;padding:0 10px;font-size:13px;font-weight:600;}}"
                f"{kind}:focus{{border-color:{AMBER};}}")

    def _toggle_block(self, label, hint):
        cb = make_checkbox(label, size=17, font_size=12)
        hl = QLabel(hint); hl.setWordWrap(True)
        hl.setStyleSheet(f"color:{MUTED};font-size:11px;margin-left:25px;")
        g = QVBoxLayout(); g.setSpacing(3); g.addWidget(cb); g.addWidget(hl)
        return cb, g

    def _toggle_frame(self):
        box = QFrame()
        box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        v = QVBoxLayout(box); v.setContentsMargins(14,12,14,12); v.setSpacing(10)
        return box, v

    # ── Setup → Business ────────────────────────────────────────────
    def _build_business_tab(self):
        scroll, fw, lay = self._settings_page("Business Information")
        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.biz_name = make_upper_textbox("e.g. JOHN'S SUPERMARKET", 2, self._box_style())
        form.addRow(self._flabel("Business Name"), self.biz_name)
        form.addRow("", self._fhint("Press Enter to start a new line - each line prints on its own line, centred. "
                                    "A line that is too long wraps by itself."))
        self.biz_subtitle = self._finp("e.g. PORTMORE BRANCH")
        form.addRow(self._flabel("Second Line"), self.biz_subtitle)
        form.addRow("", self._fhint("Optional. Printed under the name in regular type (a branch, or a tagline)."))
        self.biz_address = make_upper_textbox("e.g.\n12 MAIN STREET\nPORTMORE, ST. CATHERINE", 4, self._box_style())
        form.addRow(self._flabel("Address"), self.biz_address)
        form.addRow("", self._fhint("One line per printed line, e.g. street, town, parish. "
                                    "A line that is too long wraps by itself."))
        self.biz_phone   = self._finp("Phone");           form.addRow(self._flabel("Phone"),         self.biz_phone)
        self.biz_email   = self._finp("Email");           form.addRow(self._flabel("Email"),         self.biz_email)
        self.biz_tax_id  = self._finp("Tax ID / TRN");    form.addRow(self._flabel("Tax ID"),        self.biz_tax_id)
        self.biz_footer  = self._finp("e.g. Thank you!"); form.addRow(self._flabel("Receipt Footer"),self.biz_footer)
        lay.addLayout(form)
        page = self._settings_footer(scroll, fw, lay, "biz_feedback", "💾  Save Business Info", self._biz_save)
        self._biz_load(); self._biz_clean = self._biz_state()
        return page

    # ── Setup → Tax & Currency ──────────────────────────────────────
    def _build_tax_tab(self):
        scroll, fw, lay = self._settings_page("Tax & Currency")
        form = QFormLayout(); form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.biz_gct = QDoubleSpinBox(); self.biz_gct.setRange(0,100); self.biz_gct.setDecimals(2)
        self.biz_gct.setSuffix("  %"); self.biz_gct.setFixedHeight(36); self.biz_gct.setFixedWidth(140)
        self.biz_gct.setStyleSheet(self._spin_style())
        form.addRow(self._flabel("GCT / Tax Rate"),
                    self._hinted(self.biz_gct, "Applied to all GCT-applicable products at checkout."))
        self.tax_currency = self._finp("e.g. $  or  J$", uppercase=False)
        self.tax_currency.setMaxLength(5); self.tax_currency.setFixedWidth(140)
        form.addRow(self._flabel("Currency symbol"),
                    self._hinted(self.tax_currency, "Shown on the cashier screen, receipts and price tags."))
        self.tax_terminal = self._finp("e.g. T01  or  MAIN")
        self.tax_terminal.setMaxLength(10); self.tax_terminal.setFixedWidth(200)
        form.addRow(self._flabel("Terminal ID"),
                    self._hinted(self.tax_terminal,
                                 "Letters and numbers only, up to 10 characters. It prefixes every receipt "
                                 "number (T01-0001). Give each terminal its own ID."))
        lay.addLayout(form)
        page = self._settings_footer(scroll, fw, lay, "tax_feedback", "💾  Save Tax && Currency", self._tax_save)
        self._tax_load(); self._tax_clean = self._tax_state()
        return page

    # ── Setup → Checkout & Appearance ───────────────────────────────
    def _build_checkout_tab(self):
        scroll, fw, lay = self._settings_page("Checkout & Appearance")
        form = QFormLayout(); form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.biz_theme = QComboBox(); self.biz_theme.setFixedHeight(36); self.biz_theme.setFixedWidth(200)
        for key, label in (("amber", "Amber (default)"), ("blue", "Blue"),
                           ("green", "Green"), ("high_contrast", "High contrast")):
            self.biz_theme.addItem(label, key)
        form.addRow(self._flabel("Colour theme"),
                    self._hinted(self.biz_theme, "Takes effect the next time the program starts."))
        self.biz_quick_cash = self._finp("e.g. 5, 10, 20, 50", uppercase=False)
        form.addRow(self._flabel("Quick-cash amounts"),
                    self._hinted(self.biz_quick_cash, "Quick-cash buttons at checkout (the first 4 are shown)."))
        lay.addLayout(form)
        page = self._settings_footer(scroll, fw, lay, "chk_feedback", "💾  Save Checkout && Appearance", self._chk_save)
        self._chk_load(); self._chk_clean = self._chk_state()
        return page

    # ── Setup → Permissions ─────────────────────────────────────────
    def _build_permissions_tab(self):
        scroll, fw, lay = self._settings_page("Cashier Permissions")
        box, pb = self._toggle_frame()
        self.perm_require_remove_auth, g = self._toggle_block(
            "Require supervisor authorisation to remove items from cart",
            "When enabled, cashiers must have a supervisor enter their password to remove any cart item.")
        pb.addLayout(g)
        self.perm_session_gate, g = self._toggle_block(
            "Require cashiers to open a session before selling",
            "When enabled, cashiers see a session gate on login and cannot ring sales until a session is opened.")
        pb.addLayout(g)
        self.perm_cart_qty_edit, g = self._toggle_block(
            "Allow cashiers to edit item quantity directly in the cart",
            "When enabled, cashiers can double-click the Qty cell in the cart to change the quantity.")
        pb.addLayout(g)
        lay.addWidget(box)
        page = self._settings_footer(scroll, fw, lay, "perm_feedback", "💾  Save Permissions", self._perm_save)
        self._perm_load(); self._perm_clean = self._perm_state()
        return page

    # ── Inventory → Stock Settings ──────────────────────────────────
    def _build_stock_settings_tab(self):
        scroll, fw, lay = self._settings_page("Stock Settings")
        box, pb = self._toggle_frame()
        self.perm_stock_tracking, g = self._toggle_block(
            "Enable stock tracking",
            "When enabled, stock is decremented on every sale and incremented on voids/refunds.")
        pb.addLayout(g)
        self.perm_low_stock, g = self._toggle_block(
            "Show low stock warning when adding items to cart",
            "When enabled, cashiers see a warning if a product's stock is at or below the threshold.")
        pb.addLayout(g)
        ls_row = QHBoxLayout(); ls_row.setContentsMargins(22, 0, 0, 0); ls_row.setSpacing(8)
        lbl = QLabel("Threshold:"); lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;")
        self.perm_low_stock_threshold = QSpinBox()
        self.perm_low_stock_threshold.setRange(1, 999); self.perm_low_stock_threshold.setValue(5)
        self.perm_low_stock_threshold.setFixedSize(70, 28)
        self.perm_low_stock_threshold.setStyleSheet(self._input_style())
        self.perm_low_stock_threshold.setEnabled(False)
        units = QLabel("units or fewer"); units.setStyleSheet(f"color:{MUTED};font-size:11px;")
        ls_row.addWidget(lbl); ls_row.addWidget(self.perm_low_stock_threshold); ls_row.addWidget(units); ls_row.addStretch()
        pb.addLayout(ls_row)
        self.perm_low_stock.toggled.connect(self.perm_low_stock_threshold.setEnabled)
        lay.addWidget(box)
        page = self._settings_footer(scroll, fw, lay, "stk_feedback", "💾  Save Stock Settings", self._stk_save)
        self._stk_load(); self._stk_clean = self._stk_state()
        return page

    # ── Data → PostgreSQL ───────────────────────────────────────────
    def _build_postgres_tab(self):
        page = self._build_pg_panel()
        self._pg_clean = self._pg_state()
        return page

    def _build_groups_panel_page(self):
        return self._build_groups_panel()

    def _build_groups_panel(self):
        """Groups & Discount Levels sub-tab."""
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(fw); lay.setContentsMargins(20,20,20,20); lay.setSpacing(14)

        lay.addWidget(self._section_lbl("Product Groups  (set profit margin for auto pricing)"))
        lay.addWidget(self._hdiv())
        self.groups_table = QTableWidget(); self.groups_table.setColumnCount(2)
        self.groups_table.setHorizontalHeaderLabels(["Group Name","Profit Margin %"])
        self.groups_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.groups_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.groups_table.setFixedHeight(180)
        self.groups_table.verticalHeader().setVisible(False); self.groups_table.setShowGrid(False)
        self.groups_table.setStyleSheet(self._table_style())
        # Only margin column (col 1) is editable
        self.groups_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        lay.addWidget(self.groups_table)
        grp_row = QHBoxLayout(); grp_row.setSpacing(8)
        self.new_group_inp = QLineEdit(); self.new_group_inp.setFixedHeight(32)
        self.new_group_inp.setPlaceholderText("New group name…")
        self.new_group_inp.setStyleSheet(self._input_style())
        add_grp = QPushButton("Add Group"); add_grp.setFixedHeight(32)
        add_grp.setCursor(Qt.CursorShape.PointingHandCursor)
        add_grp.setStyleSheet(self._accent_btn()); add_grp.clicked.connect(self._add_group)
        del_grp = QPushButton("Delete Selected"); del_grp.setFixedHeight(32)
        del_grp.setCursor(Qt.CursorShape.PointingHandCursor)
        del_grp.setStyleSheet(
            f"QPushButton{{background:{RED_LIGHT};color:{RED};border:none;"
            f"border-radius:16px;font-size:11px;padding:0 12px;outline:none;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:pressed{{background:#7a1f1f;color:white;}}"
        )
        del_grp.clicked.connect(self._delete_group)
        grp_row.addWidget(self.new_group_inp, stretch=1); grp_row.addWidget(add_grp); grp_row.addWidget(del_grp)
        lay.addLayout(grp_row)
        self._load_groups()

        lay.addWidget(self._hdiv())

        # Case product profit margin
        lay.addWidget(self._section_lbl("Case Product Pricing"))
        case_hint = QLabel(
            "Markup applied to all case products when recalculating prices. "
            "Case cost is derived from the linked single product cost \u00d7 units per case."
        )
        case_hint.setStyleSheet(f"color:{MUTED};font-size:11px;"); case_hint.setWordWrap(True)
        lay.addWidget(case_hint)
        case_row = QHBoxLayout(); case_row.setSpacing(10)
        self.case_profit_spin = QDoubleSpinBox()
        self.case_profit_spin.setRange(0, 200); self.case_profit_spin.setDecimals(2)
        self.case_profit_spin.setSuffix("  %"); self.case_profit_spin.setFixedHeight(36)
        self.case_profit_spin.setFixedWidth(140)
        self.case_profit_spin.setStyleSheet(
            f"QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:13px;font-weight:600;}}"
            f"QDoubleSpinBox:focus{{border-color:{AMBER};}}"
        )
        try:
            from core.db_config import get as cfg_get
            self.case_profit_spin.setValue(float(cfg_get("case_profit_pct", "0.10")) * 100)
        except Exception:
            self.case_profit_spin.setValue(10.0)
        recalc_btn = QPushButton("\u21bb  Recalculate All Cases Now")
        recalc_btn.setFixedHeight(34)
        recalc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        recalc_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER_TEXT_ON_WHITE};border:1px solid {AMBER};"
            f"border-radius:17px;font-size:11px;padding:0 14px;outline:none;}}"
            f"QPushButton:hover{{background:{AMBER_LIGHTEST};}}"
            f"QPushButton:pressed{{background:{AMBER};color:{DARK};}}"
        )
        recalc_btn.clicked.connect(self._recalculate_cases_now)
        case_row.addWidget(self._flabel("Case Markup:")); case_row.addWidget(self.case_profit_spin)
        case_row.addWidget(recalc_btn); case_row.addStretch()
        lay.addLayout(case_row)

        lay.addWidget(self._hdiv())
        lay.addWidget(self._section_lbl("Discount Levels"))
        disc_hint = QLabel("Set the quantity threshold and percentage discount for each level.")
        disc_hint.setStyleSheet(f"color:{MUTED};font-size:11px;"); lay.addWidget(disc_hint)
        self._disc_rows = []
        for lvl in range(1, 3):
            box = QFrame(); box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
            bl = QHBoxLayout(box); bl.setContentsMargins(14,10,14,10); bl.setSpacing(14)
            lbl = QLabel(f"Level {lvl}"); lbl.setFixedWidth(60)
            lbl.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;")
            pct = QDoubleSpinBox(); pct.setRange(0,100); pct.setDecimals(2); pct.setSuffix("  % off")
            pct.setFixedHeight(34); pct.setFixedWidth(120)
            pct.setStyleSheet(f"QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 8px;font-size:13px;}}QDoubleSpinBox:focus{{border-color:{AMBER};}}")
            qty = QSpinBox(); qty.setRange(1,9999); qty.setPrefix("min qty:  ")
            qty.setFixedHeight(34); qty.setFixedWidth(140)
            qty.setStyleSheet(f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 8px;font-size:13px;}}QSpinBox:focus{{border-color:{AMBER};}}")
            bl.addWidget(lbl); bl.addWidget(pct); bl.addWidget(qty); bl.addStretch()
            lay.addWidget(box); self._disc_rows.append((pct, qty))
        self._load_discount_levels()

        lay.addStretch()
        disc_save = QPushButton("💾  Save Groups && Discounts"); disc_save.setFixedHeight(38)
        disc_save.setStyleSheet(self._accent_btn())
        disc_save.clicked.connect(self._groups_disc_save)
        lay.addWidget(disc_save)
        scroll.setWidget(fw)
        self._grp_clean = self._grp_state()
        return scroll

    def _groups_disc_save(self):
        # Save profit margins for each group row
        for row in range(self.groups_table.rowCount()):
            name_item   = self.groups_table.item(row, 0)
            margin_item = self.groups_table.item(row, 1)
            if not name_item or not margin_item: continue
            group_id = name_item.data(Qt.ItemDataRole.UserRole)
            if not group_id: continue
            # Parse margin — accept "30", "30%", "0.30"
            raw = margin_item.text().strip().rstrip("%")
            try:
                val = float(raw)
                # If entered as percentage (e.g. 30) convert to decimal (0.30)
                margin = val / 100 if val > 1 else val
            except ValueError:
                continue
            update_group_margin(group_id, margin)

        # Save case profit % and recalculate all cases
        case_pct = self.case_profit_spin.value() / 100
        from core.db_config import set as cfg_set
        cfg_set("case_profit_pct", str(case_pct))
        n_cases = recalculate_all_cases(case_pct)

        self._save_discount_levels()
        self._load_groups()   # refresh display with updated margins
        self._grp_clean = self._grp_state()

        msg = "Groups, margins, and discount levels saved.\nSelling prices have been recalculated."
        if n_cases:
            msg += f"\n{n_cases} case product{'s' if n_cases != 1 else ''} repriced at {self.case_profit_spin.value():.2f}% markup."
        QMessageBox.information(self, "Saved", msg)

    def _recalculate_cases_now(self):
        """Immediately recalculate all case products using the current spinbox value."""
        case_pct = self.case_profit_spin.value() / 100
        from core.db_config import set as cfg_set
        cfg_set("case_profit_pct", str(case_pct))
        n = recalculate_all_cases(case_pct)
        if n:
            QMessageBox.information(
                self, "Cases Recalculated",
                f"{n} case product{'s' if n != 1 else ''} repriced.\n"
                f"Markup: {self.case_profit_spin.value():.2f}%"
            )
        else:
            QMessageBox.information(self, "Cases Recalculated",
                "No case products found with a linked single product and cost > 0.")

    def _build_pg_panel(self):
        """PostgreSQL connection sub-tab."""
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(fw); lay.setContentsMargins(20,20,20,20); lay.setSpacing(14)

        lay.addWidget(self._section_lbl("PostgreSQL External Database"))
        lay.addWidget(self._hdiv())
        desc = QLabel(
            "When enabled, the POS will attempt to sync data with a PostgreSQL server "
            "over your network. Leave blank to use local SQLite only."
        )
        desc.setWordWrap(True); desc.setStyleSheet(f"color:{MUTED};font-size:11px;"); lay.addWidget(desc)

        self.pg_enabled = make_checkbox("Enable PostgreSQL sync", font_size=13)
        lay.addWidget(self.pg_enabled)
        lay.addWidget(self._hdiv())

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.pg_host = self._finp("e.g. 192.168.1.100 or hostname")
        self.pg_port = QSpinBox(); self.pg_port.setRange(1,65535); self.pg_port.setValue(5432)
        self.pg_port.setFixedHeight(34); self.pg_port.setFixedWidth(120)
        self.pg_port.setStyleSheet(f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:12px;}}QSpinBox:focus{{border-color:{AMBER};}}")
        self.pg_db   = self._finp("Database name")
        self.pg_user = self._finp("Username")
        self.pg_pass = self._finp("Password", uppercase=False)
        self.pg_pass.setEchoMode(QLineEdit.EchoMode.Password)

        for lbl_txt, widget in [("Host", self.pg_host),("Port", self.pg_port),
                                  ("Database", self.pg_db),("Username", self.pg_user),("Password", self.pg_pass)]:
            form.addRow(self._flabel(lbl_txt + ":"), widget)
        lay.addLayout(form)

        # Test connection button
        test_row = QHBoxLayout()
        test_btn = QPushButton("🔌  Test Connection"); test_btn.setFixedHeight(34)
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet("QPushButton{background:#EAF3FF;color:#2A6DB5;border:1px solid #2A6DB5;border-radius:17px;font-size:12px;font-weight:600;padding:0 16px;}QPushButton:hover{background:#2A6DB5;color:white;}")
        test_btn.clicked.connect(self._pg_test)
        self.pg_status = QLabel(""); self.pg_status.setStyleSheet(f"color:{MUTED};font-size:11px;")
        test_row.addWidget(test_btn); test_row.addWidget(self.pg_status); test_row.addStretch()
        lay.addLayout(test_row)

        lay.addStretch()
        self.pg_feedback = QLabel("")
        self.pg_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        self.pg_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(self.pg_feedback)
        save_btn = QPushButton("💾  Save PostgreSQL Settings"); save_btn.setFixedHeight(38)
        save_btn.setStyleSheet(self._accent_btn()); save_btn.clicked.connect(self._pg_save)
        lay.addWidget(save_btn)
        self._pg_load()
        scroll.setWidget(fw); return scroll

    def _pg_load(self):
        pg = get_pg_config()
        self.pg_enabled.setChecked(pg["enabled"])
        self.pg_host.setText(pg["host"]); self.pg_port.setValue(pg["port"])
        self.pg_db.setText(pg["database"]); self.pg_user.setText(pg["user"])
        self.pg_pass.setText(pg["password"])

    def _pg_save(self):
        try:
            save_pg_config(enabled=self.pg_enabled.isChecked(),
                           host=self.pg_host.text().strip(), port=self.pg_port.value(),
                           database=self.pg_db.text().strip(), user=self.pg_user.text().strip(),
                           password=self.pg_pass.text())
            self._pg_clean = self._pg_state()
            self.pg_feedback.setText("✓  PostgreSQL settings saved.")
            self.pg_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        except Exception as e:
            self.pg_feedback.setText(str(e))
            self.pg_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")

    def _pg_test(self):
        self.pg_status.setText("Testing…")
        try:
            import psycopg2
            conn = psycopg2.connect(host=self.pg_host.text().strip(), port=self.pg_port.value(),
                                     database=self.pg_db.text().strip(), user=self.pg_user.text().strip(),
                                     password=self.pg_pass.text(), connect_timeout=5)
            conn.close()
            self.pg_status.setText("✓  Connected successfully!")
            self.pg_status.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        except ImportError:
            self.pg_status.setText("psycopg2 not installed — run: pip install psycopg2-binary")
            self.pg_status.setStyleSheet(f"color:{RED};font-size:11px;")
        except Exception as e:
            self.pg_status.setText(f"✗  {e}")
            self.pg_status.setStyleSheet(f"color:{RED};font-size:11px;")


    # ── load / state / save for each settings page ────────────────────
    def _biz_load(self):
        b = get_business()
        self.biz_name.setPlainText(b.get("name",""))
        self.biz_subtitle.setText(b.get("subtitle",""))
        self.biz_address.setPlainText(b.get("address",""))
        self.biz_phone.setText(b.get("phone",""))
        self.biz_email.setText(b.get("email",""))
        self.biz_tax_id.setText(b.get("tax_id",""))
        self.biz_footer.setText(b.get("receipt_footer",""))

    def _tax_load(self):
        self.biz_gct.setValue(gct_rate() * 100)
        self.tax_currency.setText(get("currency_symbol", "$"))
        self.tax_terminal.setText(get("terminal_id", "01"))

    def _chk_load(self):
        i = self.biz_theme.findData(get("theme", "amber"))
        self.biz_theme.setCurrentIndex(i if i >= 0 else 0)
        self.biz_quick_cash.setText(", ".join(f"{a:g}" for a in checkout_quick_amounts()))

    def _perm_load(self):
        from core.db_config import get_bool
        self.perm_require_remove_auth.setChecked(get_bool("require_remove_auth", False))
        self.perm_session_gate.setChecked(get_bool("session_gate", False))
        self.perm_cart_qty_edit.setChecked(get_bool("allow_cart_qty_edit", False))

    def _stk_load(self):
        from core.db_config import get_bool, get_int
        low = get_bool("low_stock_warning", False)
        self.perm_low_stock.setChecked(low)
        self.perm_low_stock_threshold.setValue(get_int("low_stock_threshold", 5))
        self.perm_low_stock_threshold.setEnabled(low)
        self.perm_stock_tracking.setChecked(get_bool("stock_tracking", False))

    @staticmethod
    def _parse_quick_amounts(text: str) -> list[float]:
        parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
        if not parts:
            raise ValueError("Enter at least one quick-cash amount, e.g. 5, 10, 20, 50.")
        try:
            amounts = [float(p) for p in parts]
        except ValueError:
            raise ValueError("Quick-cash amounts must be numbers separated by commas.")
        if any(a <= 0 for a in amounts):
            raise ValueError("Quick-cash amounts must be greater than zero.")
        return amounts

    # ── unsaved-change tracking (checked on logout) ───────────────────
    def _biz_state(self):
        return (self.biz_name.toPlainText(), self.biz_subtitle.text(),
                self.biz_address.toPlainText(), self.biz_phone.text(),
                self.biz_email.text(), self.biz_tax_id.text(), self.biz_footer.text())

    def _tax_state(self):
        return (self.biz_gct.value(), self.tax_currency.text().strip(),
                self.tax_terminal.text().strip().upper())

    def _chk_state(self):
        return (self.biz_theme.currentData(), self.biz_quick_cash.text().strip())

    def _perm_state(self):
        return (self.perm_require_remove_auth.isChecked(), self.perm_session_gate.isChecked(),
                self.perm_cart_qty_edit.isChecked())

    def _stk_state(self):
        return (self.perm_stock_tracking.isChecked(), self.perm_low_stock.isChecked(),
                self.perm_low_stock_threshold.value())

    def _grp_margins_state(self):
        out = []
        for r in range(self.groups_table.rowCount()):
            n, m = self.groups_table.item(r, 0), self.groups_table.item(r, 1)
            out.append((n.text() if n else "", m.text().strip() if m else ""))
        return tuple(out)

    def _grp_state(self):
        disc = tuple((p.value(), q.value()) for p, q in getattr(self, "_disc_rows", []))
        return (self._grp_margins_state(), disc, self.case_profit_spin.value())

    def _pg_state(self):
        return (self.pg_enabled.isChecked(), self.pg_host.text(), self.pg_port.value(),
                self.pg_db.text(), self.pg_user.text(), self.pg_pass.text())

    # (clean-baseline attribute, state method, name shown in the logout warning)
    _SETTINGS_TRACKED = (
        ("_biz_clean",  "_biz_state",  "Business Info"),
        ("_tax_clean",  "_tax_state",  "Tax & Currency"),
        ("_chk_clean",  "_chk_state",  "Checkout & Appearance"),
        ("_perm_clean", "_perm_state", "Permissions"),
        ("_stk_clean",  "_stk_state",  "Stock Settings"),
        ("_grp_clean",  "_grp_state",  "Groups & Discounts"),
        ("_pg_clean",   "_pg_state",   "PostgreSQL"),
    )

    def _unsaved_sections(self) -> list[str]:
        out = super()._unsaved_sections()
        for clean_attr, state_fn, label in self._SETTINGS_TRACKED:
            if hasattr(self, clean_attr) and getattr(self, state_fn)() != getattr(self, clean_attr):
                out.append(label)
        if self._lazy.is_built("receipt") and getattr(self._lazy.page("receipt"), "_dirty", False):
            out.append("Receipt")
        if self._lazy.is_built("backup") and self._lazy.page("backup").is_dirty():
            out.append("Backup")
        return out

    def _biz_save(self):
        try:
            for label, text in (("Business name", self.biz_name.toPlainText()),
                                ("Second line",   self.biz_subtitle.text()),
                                ("Address",       self.biz_address.toPlainText())):
                if len(clean_lines(text)) > BUSINESS_TEXT_MAX:
                    raise ValueError(f"{label} is too long (the limit is {BUSINESS_TEXT_MAX} characters).")
            update_business(name=self.biz_name.toPlainText(),
                            subtitle=self.biz_subtitle.text(),
                            address=self.biz_address.toPlainText(),
                            phone=self.biz_phone.text().strip(),
                            email=self.biz_email.text().strip(),
                            tax_id=self.biz_tax_id.text().strip(),
                            receipt_footer=self.biz_footer.text().strip())
            self._biz_load()                      # show it back as it is stored and will print
            self._biz_clean = self._biz_state()
            self._flash("biz_feedback", "✓  Business info saved.")
        except Exception as e:
            self._flash("biz_feedback", str(e), ok=False)

    def _tax_save(self):
        try:
            currency = self.tax_currency.text().strip() or "$"
            tid = self.tax_terminal.text().strip().upper()
            if not tid:
                raise ValueError("Terminal ID is required.")
            if not tid.replace("-", "").isalnum():
                raise ValueError("Terminal ID must contain only letters and numbers.")
            if tid != get("terminal_id", "01").strip().upper():
                reply = QMessageBox.question(
                    self, "Change Terminal ID",
                    f"Receipts from the next sale on will be numbered {tid}-0001, {tid}-0002 …\n"
                    "Receipts already saved keep their old numbers.\n\n"
                    "Every terminal must have its own ID. Change it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return
            set_many({"gct_rate": str(self.biz_gct.value() / 100),
                      "currency_symbol": currency,
                      "terminal_id": tid})
            self._tax_load()
            self._tax_clean = self._tax_state()
            self._flash("tax_feedback", "✓  Tax & currency saved.")
        except Exception as e:
            self._flash("tax_feedback", str(e), ok=False)

    def _chk_save(self):
        try:
            quick = self._parse_quick_amounts(self.biz_quick_cash.text())
            set_many({"theme": self.biz_theme.currentData(),
                      "checkout_quick_amounts": ",".join(f"{a:g}" for a in quick)})
            self.biz_quick_cash.setText(", ".join(f"{a:g}" for a in quick))
            self._chk_clean = self._chk_state()
            self._flash("chk_feedback", "✓  Checkout & appearance saved.")
        except Exception as e:
            self._flash("chk_feedback", str(e), ok=False)

    def _perm_save(self):
        try:
            set_many({"require_remove_auth": "1" if self.perm_require_remove_auth.isChecked() else "0",
                      "session_gate":        "1" if self.perm_session_gate.isChecked() else "0",
                      "allow_cart_qty_edit": "1" if self.perm_cart_qty_edit.isChecked() else "0"})
            self._perm_clean = self._perm_state()
            self._flash("perm_feedback", "✓  Permissions saved.")
        except Exception as e:
            self._flash("perm_feedback", str(e), ok=False)

    def _stk_save(self):
        try:
            set_many({"stock_tracking":      "1" if self.perm_stock_tracking.isChecked() else "0",
                      "low_stock_warning":   "1" if self.perm_low_stock.isChecked() else "0",
                      "low_stock_threshold": str(self.perm_low_stock_threshold.value())})
            self._stk_clean = self._stk_state()
            self._flash("stk_feedback", "✓  Stock settings saved.")
        except Exception as e:
            self._flash("stk_feedback", str(e), ok=False)

    def _load_discount_levels(self):
        """Load the first two discount_levels rows (by min_qty) into the
        two editor rows. Routes through db_products.py instead of raw SQL —
        also fixes the old code's silent no-op on a fresh install where
        no rows exist yet (see _save_discount_levels, which now creates
        them on first save)."""
        try:
            from core.db_products import get_discount_levels
            levels = get_discount_levels()  # ordered by min_qty ascending
            for i, lvl in enumerate(levels[:2]):
                if i < len(self._disc_rows):
                    self._disc_rows[i][0].setValue(lvl["percent"] * 100)  # fraction -> display %
                    self._disc_rows[i][1].setValue(lvl["min_qty"])
        except Exception:
            pass

    def _save_discount_levels(self):
        """Save the two editor rows to discount_levels. Updates existing
        rows if present, otherwise creates them — so this works correctly
        on a fresh install where the table starts empty, unlike the old
        raw-SQL version which only ever UPDATEd and silently did nothing
        if no rows existed."""
        from core.db_products import get_discount_levels, add_discount_level, update_discount_level
        levels = get_discount_levels()
        for i, (pct_spin, qty_spin) in enumerate(self._disc_rows):
            pct = pct_spin.value() / 100  # display % -> stored fraction
            qty = qty_spin.value()
            if i < len(levels):
                update_discount_level(levels[i]["id"], min_qty=qty, percent=pct)
            else:
                add_discount_level(f"Level {i + 1}", qty, pct)

    def _load_groups(self):
        self.groups_table.setRowCount(0)
        for g in get_groups():
            row = self.groups_table.rowCount(); self.groups_table.insertRow(row)
            self.groups_table.setRowHeight(row, 34)
            name_item = QTableWidgetItem(g["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, g["id"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # lock name
            self.groups_table.setItem(row, 0, name_item)
            margin = g.get("profit_margin", 0) or 0
            margin_item = QTableWidgetItem(f"{float(margin)*100:.1f}")
            self.groups_table.setItem(row, 1, margin_item)

    def _reload_groups_keep_edits_state(self):
        """Reload the groups table after an add/delete (which hit the database at once)
        without hiding unsaved discount/case edits from the logout warning."""
        self._load_groups()
        old = getattr(self, "_grp_clean", None)
        if old is not None:
            self._grp_clean = (self._grp_margins_state(),) + tuple(old[1:])

    def _add_group(self):
        name = self.new_group_inp.text().strip()
        if not name: return
        try: add_group(name); self.new_group_inp.clear(); self._reload_groups_keep_edits_state()
        except Exception as e: QMessageBox.warning(self, "Error", str(e))

    def _delete_group(self):
        row = self.groups_table.currentRow()
        item = self.groups_table.item(row, 0)
        if not item: return
        gid = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Delete Group", f"Delete group '{item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_group(gid); self._reload_groups_keep_edits_state()



    def _build_dbf_import_tab(self):
        from ui.manager.dbf_import_tab import DBFImportTab
        tab = DBFImportTab(self.user, parent=self)
        tab.import_complete.connect(self._on_import_complete)
        return tab

    def _on_import_complete(self):
        """Refresh the Products list after a DBF import.

        The Products tab's add/edit form is now a pop-up (ProductDialog,
        opened on demand) rather than an always-visible panel, so there's
        no persistent group/discount combo to refresh here anymore — just
        reload the product table so imported rows show up immediately."""
        self._pg_page = 0
        # The Products tab is built lazily: if it hasn't been opened yet there is
        # nothing to reload — it will load fresh data when it is first shown.
        if self._lazy.is_built("products"):
            self._load_products(self.product_search.text())

    def _build_quickkeys_tab(self):
        from ui.shared.searchable_product_combo import SearchableProductCombo
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(10)
        hint = QLabel("Assign a product to each F-key (F1–F8). Type a product name or barcode to search — select from the results.")
        hint.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;"); lay.addWidget(hint)

        self._qk_widgets = []
        for k in get_quick_keys():
            row = QHBoxLayout(); row.setSpacing(10)
            badge = QLabel(f"F{k['slot']}"); badge.setFixedSize(40,32)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"background:{DARK_CARD};color:{AMBER};border-radius:6px;font-size:11px;font-weight:700;")
            # Same picker the Supervisor dashboard's Quick Keys tab now uses
            # (previously this file had its own separate ProductSearchWidget
            # that only filtered by name, client-side, over a fixed snapshot
            # of up to 5000 products — inconsistent with every other search
            # bar in the app, which search barcode too). Sharing one widget
            # means both dashboards behave identically here going forward.
            sw = SearchableProductCombo(
                none_label="— No product assigned —", show_price=True,
                price_field="effective_selling_price",
                exclude_cases=False, exclude_variant_members=False,
            )
            if k.get("product_id"):
                sw.set_value(k["product_id"])
            sw.setProperty("slot", k["slot"])
            row.addWidget(badge); row.addWidget(sw, stretch=1)
            lay.addLayout(row); self._qk_widgets.append(sw)

        lay.addStretch()
        save_btn = QPushButton("💾  Save Quick Keys"); save_btn.setFixedHeight(42)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(self._accent_btn()); save_btn.clicked.connect(self._qk_save_manager)
        lay.addWidget(save_btn)
        self._qk_clean = self._qk_state()   # baseline for the unsaved-changes check
        return w

    def _qk_save_manager(self):
        assignments = [
            {"slot": sw.property("slot"), "product_id": sw.selected_id()}
            for sw in self._qk_widgets
        ]
        save_quick_keys(assignments)
        self._qk_clean = self._qk_state()
        QMessageBox.information(self, "Saved", "Quick keys saved successfully.")

    # ================================================================
    # STYLE HELPERS  (duplicate from supervisor for self-containment)
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
            f"border-radius:7px;padding:0 10px;font-size:12px;outline:none;}}"
            f"QLineEdit:hover{{border-color:{AMBER_LIGHTEST if not accent else AMBER};}}"
            f"QLineEdit:focus{{border-color:{AMBER};background:#fffef9;}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
            f"QLineEdit:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}"
        )

    def _combo_style(self):
        return (
            f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;outline:none;}}"
            f"QComboBox:hover{{border-color:{AMBER_LIGHTEST};}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
            f"QComboBox QAbstractItemView{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};outline:none;"
            f"selection-background-color:{AMBER};selection-color:{DARK};}}"
        )

    def _accent_btn(self):
        # AMBER (#EF9F27) with white text measures ~2.2:1 — fails WCAG AA
        # (needs 4.5:1). DARK text on AMBER measures ~9.6:1, and matches
        # SupervisorWindow's own _accent_btn, which this was silently
        # overriding with the low-contrast version for every manager-only
        # Save button (Business Info, Printers, PostgreSQL, Groups).
        return (
            f"QPushButton{{background:{AMBER};color:{DARK};border:none;"
            f"border-radius:17px;font-size:12px;font-weight:700;padding:0 16px;outline:none;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};color:{DARK};}}"
            f"QPushButton:pressed{{background:{AMBER_DARK};color:{DARK};}}"
            f"QPushButton:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}"
        )

    def _finp(self, placeholder, uppercase=True):
        if uppercase:
            inp = self.make_upper_input(placeholder)
        else:
            inp = QLineEdit(); inp.setPlaceholderText(placeholder); inp.setFixedHeight(34)
        inp.setStyleSheet(self._input_style()); return inp

    def _box_style(self):
        """Style for the multi-line name/address boxes - matches _input_style()."""
        return (
            f"QPlainTextEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:6px 10px;font-size:12px;}}"
            f"QPlainTextEdit:hover{{border-color:{AMBER_LIGHTEST};}}"
            f"QPlainTextEdit:focus{{border-color:{AMBER};background:#fffef9;}}"
        )

    def _fhint(self, text):
        l = QLabel(text); l.setWordWrap(True)
        l.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)   # use the whole field width
        l.setStyleSheet(f"color:{MUTED};font-size:10px;"); return l

    def _flabel(self, text):
        l = QLabel(text); l.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;font-weight:600;"); return l

    def _section_lbl(self, text):
        l = QLabel(text.upper()); l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;"); return l

    def _hdiv(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;"); return f
