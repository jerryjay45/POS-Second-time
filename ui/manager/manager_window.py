"""
ui/manager/manager_window.py
Manager dashboard — inherits SupervisorWindow and prepends manager-only tabs:
  • Users     — add / edit / delete users, role assignment
  • Business  — business info, GCT %, discount levels, product groups, printer settings
  • Quick Keys — (inherited from supervisor, shown here too)
  • All supervisor tabs (Products, Reports, Transactions, Void/Refund)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QCheckBox, QAbstractItemView,
    QMessageBox, QScrollArea, QSplitter, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QFormLayout,
)
from PyQt6.QtCore  import Qt, QEvent, pyqtSignal
from PyQt6.QtGui   import QColor, QDoubleValidator

from ui.supervisor.supervisor_window import SupervisorWindow
from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_4, DARK_CARD,
    WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN, GREEN_LIGHT, BLUE,
)
from core.db_users    import add_user, update_user, delete_user, get_users, get_user_by_id
from core.db_config   import (
    get_business, update_business, get, set as cfg_set, set_many,
    gct_rate, get_pg_config, save_pg_config, get_quick_keys, save_quick_keys,
)
from core.db_products import get_products, get_product_by_id, get_groups, add_group, delete_group, update_group_margin, recalculate_all_cases


# ================================================================
# PRODUCT SEARCH WIDGET  (Google-style live search dropdown)
# ================================================================

class ProductSearchWidget(QWidget):
    """
    Type to filter products → inline dropdown → click/Enter to confirm.
    Call currentData() to get selected product ID (None = unassigned).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_pid = None
        self._all_products = []   # [(id, name, price), …]
        self._build()

    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        self.inp = QLineEdit(); self.inp.setFixedHeight(34)
        self.inp.setPlaceholderText("Search products…")
        self.inp.setStyleSheet(f"""
            QLineEdit{{background:{WHITE};color:{DARK_CARD};
            border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:12px;}}
            QLineEdit:focus{{border-color:{AMBER};}}
        """)
        self.inp.textChanged.connect(self._on_text)
        self.inp.installEventFilter(self)

        self.lst = QListWidget(); self.lst.setVisible(False); self.lst.setMaximumHeight(160)
        self.lst.setStyleSheet(f"""
            QListWidget{{background:{WHITE};color:{DARK_CARD};
            border:1.5px solid {AMBER};border-radius:0 0 7px 7px;border-top:none;font-size:12px;}}
            QListWidget::item{{padding:7px 12px;border-bottom:1px solid {BORDER_LIGHT};}}
            QListWidget::item:selected{{background:{AMBER};color:white;}}
            QListWidget::item:hover{{background:{AMBER_LIGHTEST};}}
        """)
        self.lst.itemClicked.connect(self._on_click)
        self.lst.installEventFilter(self)
        lay.addWidget(self.inp); lay.addWidget(self.lst)

    def set_products(self, products):
        self._all_products = products

    def set_selection(self, pid, display):
        self._selected_pid = pid
        self.inp.blockSignals(True); self.inp.setText(display); self.inp.blockSignals(False)
        self.lst.setVisible(False)

    def clear_selection(self):
        self._selected_pid = None
        self.inp.blockSignals(True); self.inp.clear(); self.inp.blockSignals(False)
        self.lst.setVisible(False)

    def currentData(self): return self._selected_pid

    def _on_text(self, text):
        self._selected_pid = None; q = text.strip().lower()
        if not q: self.lst.setVisible(False); return
        matches = [(pid,name,price) for pid,name,price in self._all_products if q in name.lower()][:10]
        self.lst.clear()
        if matches:
            for pid, name, price in matches:
                item = QListWidgetItem(f"{name}  —  ${price:.2f}")
                item.setData(Qt.ItemDataRole.UserRole, (pid, f"{name}  (${price:.2f})"))
                self.lst.addItem(item)
        else:
            no = QListWidgetItem("  No products found"); no.setForeground(QColor(MUTED))
            no.setFlags(no.flags() & ~Qt.ItemFlag.ItemIsSelectable); self.lst.addItem(no)
        self.lst.setVisible(True)

    def _on_click(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data: return
        pid, display = data; self._selected_pid = pid
        self.inp.blockSignals(True); self.inp.setText(display); self.inp.blockSignals(False)
        self.lst.setVisible(False)

    def eventFilter(self, obj, event):
        if obj is self.inp and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down and self.lst.isVisible():
                self.lst.setCurrentRow(0); self.lst.setFocus(); return True
            if event.key() == Qt.Key.Key_Escape:
                self.lst.setVisible(False); return True
        if obj is self.lst and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                cur = self.lst.currentItem()
                if cur: self._on_click(cur); return True
            if event.key() == Qt.Key.Key_Up and self.lst.currentRow()==0:
                self.inp.setFocus(); return True
        return super().eventFilter(obj, event)


# ================================================================
# MANAGER WINDOW
# ================================================================

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
        self._clock.setStyleSheet(f"color:{MUTED};font-size:11px;font-family:'DM Mono',monospace;")
        logout = QPushButton("Logout  ↗"); logout.setFixedHeight(30)
        logout.setCursor(Qt.CursorShape.PointingHandCursor)
        logout.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:white;border:none;
            border-radius:15px;font-size:11px;font-weight:700;padding:0 16px;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        logout.clicked.connect(self._handle_logout)
        lay.addWidget(left); lay.addStretch(); lay.addWidget(self._clock); lay.addStretch(); lay.addWidget(logout)
        return bar

    def _build_manager_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane{{background:{WARM_WHITE};border:none;}}
            QTabBar::tab{{background:{WHITE};color:{LABEL_TEXT};border:none;
            border-bottom:2px solid transparent;padding:10px 16px;
            font-size:12px;font-weight:500;margin-right:2px;}}
            QTabBar::tab:selected{{color:{DARK_CARD};border-bottom:2px solid {AMBER};font-weight:700;}}
            QTabBar::tab:hover{{color:{DARK_CARD};}}
        """)
        # Manager-only tabs first
        self.tabs.addTab(self._build_users_tab(),    "👥  Users")
        self.tabs.addTab(self._build_business_tab(), "🏢  Business")
        # Then all supervisor tabs
        self.tabs.addTab(self._build_products_tab(),     "📦  Products")
        self.tabs.addTab(self._build_reports_tab(),      "📊  Reports")
        self.tabs.addTab(self._build_transactions_tab(), "🧾  Transactions")
        from ui.supervisor.void_refund_tab import VoidRefundTab
        self._void_refund_tab = VoidRefundTab(user=self.user, parent=self)
        self.tabs.addTab(self._void_refund_tab,          "↩  Void / Refund")
        self.tabs.addTab(self._build_stock_tab(),        "📊  Stock")
        self.tabs.addTab(self._build_price_tag_tab(),    "🏷  Price Tags")
        self.tabs.addTab(self._build_quickkeys_tab(),    "⌨  Quick Keys")
        self.tabs.addTab(self._build_dbf_import_tab(),   "📥  Import")
        self.tabs.setCurrentIndex(0)
        return self.tabs

    # ================================================================
    # USERS TAB
    # ================================================================

    def _build_users_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QHBoxLayout(w); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)

        # Left: user list
        left = QFrame()
        left.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        ll = QVBoxLayout(left); ll.setContentsMargins(10,10,10,10); ll.setSpacing(8)

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
        add_btn.setStyleSheet(self._accent_btn()); add_btn.clicked.connect(self._usr_new_form)

        tb.addWidget(self.usr_search, stretch=1)
        tb.addWidget(self.usr_role_filter); tb.addWidget(add_btn)
        ll.addLayout(tb)

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
        self.usr_table.selectionModel().selectionChanged.connect(self._usr_on_row_selected)
        ll.addWidget(self.usr_table, stretch=1)

        # Right: user form
        right = QFrame(); right.setFixedWidth(280)
        right.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        rl = QVBoxLayout(right); rl.setContentsMargins(16,16,16,16); rl.setSpacing(10)

        self.usr_form_title = QLabel("Add User")
        self.usr_form_title.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;")
        rl.addWidget(self.usr_form_title)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;"); rl.addWidget(sep)

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.usr_f_fullname = self.make_upper_input("Full name"); self.usr_f_fullname.setStyleSheet(self._input_style())
        self.usr_f_username = self.make_upper_input("Login username"); self.usr_f_username.setStyleSheet(self._input_style())
        self.usr_f_password = QLineEdit(); self.usr_f_password.setFixedHeight(34)
        self.usr_f_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.usr_f_password.setPlaceholderText("Password (leave blank to keep)")
        self.usr_f_password.setStyleSheet(self._input_style())
        # Force password to uppercase as typed
        self.usr_f_password.textChanged.connect(
            lambda t: self.usr_f_password.setText(t.upper()) if t != t.upper() else None
        )
        self.usr_f_role = QComboBox(); self.usr_f_role.setFixedHeight(34)
        self.usr_f_role.addItems(["cashier","supervisor","manager"])
        self.usr_f_role.setStyleSheet(self._combo_style())
        self.usr_f_active = QCheckBox("Active"); self.usr_f_active.setChecked(True)
        self.usr_f_active.setStyleSheet(f"color:{DARK_CARD};font-size:12px;")

        for lbl_txt, widget in [("Full Name", self.usr_f_fullname),("Username", self.usr_f_username),
                                  ("Password", self.usr_f_password),("Role", self.usr_f_role),("", self.usr_f_active)]:
            lbl = QLabel(lbl_txt); lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;")
            form.addRow(lbl, widget)
        rl.addLayout(form)
        rl.addStretch()

        self.usr_feedback = QLabel("")
        self.usr_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        self.usr_feedback.setWordWrap(True); self.usr_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.usr_feedback)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.usr_save_btn = QPushButton("💾  Save"); self.usr_save_btn.setFixedHeight(34)
        self.usr_save_btn.setStyleSheet(self._accent_btn()); self.usr_save_btn.clicked.connect(self._usr_save)
        self.usr_delete_btn = QPushButton("🗑  Delete"); self.usr_delete_btn.setFixedHeight(34)
        self.usr_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.usr_delete_btn.setStyleSheet(f"QPushButton{{background:{RED_LIGHT};color:{RED};border:none;border-radius:17px;font-size:12px;font-weight:600;padding:0 12px;}}QPushButton:hover{{background:{RED};color:white;}}QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};}}")
        self.usr_delete_btn.setEnabled(False); self.usr_delete_btn.clicked.connect(self._usr_delete)
        self.usr_clear_btn = QPushButton("Clear"); self.usr_clear_btn.setFixedHeight(34)
        self.usr_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.usr_clear_btn.setStyleSheet(f"QPushButton{{background:{WARM_WHITE};color:{LABEL_TEXT};border:1px solid {BORDER};border-radius:17px;font-size:12px;}}QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}")
        self.usr_clear_btn.clicked.connect(self._usr_new_form)
        btn_row.addWidget(self.usr_save_btn, stretch=1)
        btn_row.addWidget(self.usr_delete_btn); btn_row.addWidget(self.usr_clear_btn)
        rl.addLayout(btn_row)

        lay.addWidget(left, stretch=1); lay.addWidget(right)
        self._usr_editing_id = None; self._usr_all_users = []
        self._usr_load(); return w

    def _usr_load(self):
        self._usr_all_users = get_users()
        self._usr_populate(self._usr_all_users)

    def _usr_populate(self, users):
        self.usr_table.setRowCount(0)
        role_colors = {"cashier":BLUE,"supervisor":AMBER,"manager":RED}
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
            edit.setStyleSheet(f"QPushButton{{background:transparent;color:{AMBER};border:1px solid {AMBER};border-radius:5px;font-size:11px;}}QPushButton:hover{{background:{AMBER};color:white;}}")
            edit.clicked.connect(lambda _, uid=u["id"]: self._usr_load_form(uid))
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

    def _usr_on_row_selected(self):
        row = self.usr_table.currentRow(); item = self.usr_table.item(row, 0)
        if item: self._usr_load_form(item.data(Qt.ItemDataRole.UserRole))

    def _usr_load_form(self, uid):
        u = next((u for u in self._usr_all_users if u["id"]==uid), None)
        if not u: return
        self._usr_editing_id = uid
        self.usr_form_title.setText(f"Edit: {u['full_name']}")
        self.usr_f_fullname.setText(u["full_name"]); self.usr_f_username.setText(u["username"])
        self.usr_f_password.clear()
        idx = self.usr_f_role.findText(u["role"])
        if idx >= 0: self.usr_f_role.setCurrentIndex(idx)
        self.usr_f_active.setChecked(bool(u["is_active"]))
        self.usr_delete_btn.setEnabled(uid != self.user["id"])
        self.usr_feedback.setText("")

    def _usr_new_form(self):
        self._usr_editing_id = None
        self.usr_form_title.setText("Add User")
        for inp in [self.usr_f_fullname, self.usr_f_username, self.usr_f_password]: inp.clear()
        self.usr_f_role.setCurrentIndex(0); self.usr_f_active.setChecked(True)
        self.usr_delete_btn.setEnabled(False); self.usr_feedback.setText("")
        self.usr_table.clearSelection()

    def _usr_save(self):
        full_name = self.usr_f_fullname.text().strip()
        username  = self.usr_f_username.text().strip()
        password  = self.usr_f_password.text()
        role      = self.usr_f_role.currentText()
        is_active = self.usr_f_active.isChecked()
        if not full_name or not username:
            self._usr_err("Full name and username are required."); return
        if self._usr_editing_id is None and not password:
            self._usr_err("Password required for new user."); return
        try:
            if self._usr_editing_id is None:
                add_user(full_name, username, password, role, is_active)
                self._usr_ok(f"User '{full_name}' created.")
            else:
                update_user(self._usr_editing_id, full_name=full_name, username=username,
                            password=password or None, role=role, is_active=is_active)
                self._usr_ok(f"User '{full_name}' updated.")
            self._usr_load(); self._usr_new_form()
        except Exception as e:
            self._usr_err(str(e))

    def _usr_delete(self):
        if not self._usr_editing_id or self._usr_editing_id == self.user["id"]: return
        u = next((u for u in self._usr_all_users if u["id"]==self._usr_editing_id), None)
        name = u["full_name"] if u else f"#{self._usr_editing_id}"
        reply = QMessageBox.question(self, "Delete User", f"Delete '{name}'?\n\nTransaction history will not be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        try:
            delete_user(self._usr_editing_id); self._usr_load(); self._usr_new_form()
        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", str(e))

    def _usr_ok(self, msg):
        self.usr_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        self.usr_feedback.setText(msg)

    def _usr_err(self, msg):
        self.usr_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")
        self.usr_feedback.setText(msg)

    # ================================================================
    # BUSINESS TAB
    # ================================================================

    def _build_business_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        sub = QTabWidget()
        sub.setStyleSheet(f"""
            QTabWidget::pane{{background:{WARM_WHITE};border:none;border-top:1px solid {BORDER};}}
            QTabBar::tab{{background:{WARM_WHITE};color:{LABEL_TEXT};border:none;
            border-bottom:2px solid transparent;padding:8px 16px;
            font-size:11px;font-weight:500;}}
            QTabBar::tab:selected{{color:{DARK_CARD};border-bottom:2px solid {AMBER};font-weight:700;}}
            QTabBar::tab:hover{{color:{DARK_CARD};}}
        """)
        sub.addTab(self._build_biz_info_panel(),      "🏢  Business Info")
        sub.addTab(self._build_groups_panel(),        "📂  Groups & Discounts")
        sub.addTab(self._build_printers_panel(),      "🖨  Printers")
        sub.addTab(self._build_pg_panel(),            "🗄  PostgreSQL")
        lay.addWidget(sub)
        return w

    def _build_biz_info_panel(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(fw); lay.setContentsMargins(20,20,20,20); lay.setSpacing(14)

        lay.addWidget(self._section_lbl("Business Information"))
        lay.addWidget(self._hdiv())

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.biz_name    = self._finp("Business name");   form.addRow(self._flabel("Business Name"), self.biz_name)
        self.biz_address = self._finp("Address");         form.addRow(self._flabel("Address"),       self.biz_address)
        self.biz_phone   = self._finp("Phone");           form.addRow(self._flabel("Phone"),         self.biz_phone)
        self.biz_email   = self._finp("Email");           form.addRow(self._flabel("Email"),         self.biz_email)
        self.biz_tax_id  = self._finp("Tax ID / TRN");    form.addRow(self._flabel("Tax ID"),        self.biz_tax_id)
        self.biz_footer  = self._finp("e.g. Thank you!"); form.addRow(self._flabel("Receipt Footer"),self.biz_footer)
        lay.addLayout(form)

        lay.addWidget(self._hdiv())
        lay.addWidget(self._section_lbl("GCT / Tax Rate"))
        gct_row = QHBoxLayout(); gct_row.setSpacing(10)
        self.biz_gct = QDoubleSpinBox(); self.biz_gct.setRange(0,100); self.biz_gct.setDecimals(2)
        self.biz_gct.setSuffix("  %"); self.biz_gct.setFixedHeight(36); self.biz_gct.setFixedWidth(140)
        self.biz_gct.setStyleSheet(f"QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:13px;font-weight:600;}}QDoubleSpinBox:focus{{border-color:{AMBER};}}")
        self.biz_gct.setValue(gct_rate()*100)
        gct_hint = QLabel("Applied to all GCT-applicable products at checkout")
        gct_hint.setStyleSheet(f"color:{MUTED};font-size:11px;")
        gct_row.addWidget(self._flabel("Rate:")); gct_row.addWidget(self.biz_gct); gct_row.addWidget(gct_hint); gct_row.addStretch()
        lay.addLayout(gct_row)

        # Cashier permissions
        lay.addWidget(self._hdiv())
        lay.addWidget(self._section_lbl("Cashier Permissions"))
        perm_box = QFrame()
        perm_box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        pb = QVBoxLayout(perm_box); pb.setContentsMargins(14,12,14,12); pb.setSpacing(6)
        def _perm_toggle(label, hint):
            cb = QCheckBox(label)
            cb.setStyleSheet(
                f"QCheckBox{{color:{DARK_CARD};font-size:12px;font-weight:500;}}"
                f"QCheckBox::indicator{{width:16px;height:16px;border:1px solid {BORDER};"
                f"border-radius:3px;background:{WHITE};}}"
                f"QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}"
            )
            hl = QLabel(hint); hl.setWordWrap(True)
            hl.setStyleSheet(f"color:{MUTED};font-size:11px;margin-left:22px;")
            return cb, hl

        self.perm_require_remove_auth, ra_hint = _perm_toggle(
            "Require supervisor authorisation to remove items from cart",
            "When enabled, cashiers must have a supervisor enter their password to remove any cart item."
        )
        self.perm_session_gate, sg_hint = _perm_toggle(
            "Require cashiers to open a session before selling",
            "When enabled, cashiers see a session gate on login and cannot ring sales until a session is opened."
        )
        self.perm_cart_qty_edit, cq_hint = _perm_toggle(
            "Allow cashiers to edit item quantity directly in the cart",
            "When enabled, cashiers can double-click the Qty cell in the cart to change the quantity."
        )

        # Low stock warning toggle + threshold spinbox
        self.perm_low_stock, ls_hint = _perm_toggle(
            "Show low stock warning when adding items to cart",
            "When enabled, cashiers see a warning if a product's stock is at or below the threshold."
        )
        self.perm_stock_tracking, st_hint = _perm_toggle(
            "Enable stock tracking",
            "When enabled, stock is decremented on every sale and incremented on voids/refunds."
        )
        ls_row = QHBoxLayout()
        ls_row.setContentsMargins(22, 0, 0, 0)
        ls_row.setSpacing(8)
        ls_threshold_lbl = QLabel("Threshold:")
        ls_threshold_lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;")
        self.perm_low_stock_threshold = QSpinBox()
        self.perm_low_stock_threshold.setMinimum(1)
        self.perm_low_stock_threshold.setMaximum(999)
        self.perm_low_stock_threshold.setValue(5)
        self.perm_low_stock_threshold.setFixedWidth(70)
        self.perm_low_stock_threshold.setFixedHeight(28)
        self.perm_low_stock_threshold.setStyleSheet(self._input_style())
        self.perm_low_stock_threshold.setEnabled(False)
        ls_units_lbl = QLabel("units or fewer")
        ls_units_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        ls_row.addWidget(ls_threshold_lbl)
        ls_row.addWidget(self.perm_low_stock_threshold)
        ls_row.addWidget(ls_units_lbl)
        ls_row.addStretch()
        # Enable/disable threshold spinbox with the checkbox
        self.perm_low_stock.toggled.connect(self.perm_low_stock_threshold.setEnabled)

        for widget in [
            self.perm_require_remove_auth, ra_hint,
            self.perm_session_gate,        sg_hint,
            self.perm_cart_qty_edit,       cq_hint,
            self.perm_low_stock,           ls_hint,
            self.perm_stock_tracking,      st_hint,
        ]:
            pb.addWidget(widget)
        pb.addLayout(ls_row)
        lay.addWidget(perm_box)

        lay.addStretch()
        self.biz_feedback = QLabel("")
        self.biz_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        self.biz_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.biz_feedback)
        save_btn = QPushButton("💾  Save Business Info"); save_btn.setFixedHeight(38)
        save_btn.setStyleSheet(self._accent_btn()); save_btn.clicked.connect(self._biz_save)
        lay.addWidget(save_btn)

        scroll.setWidget(fw); self._biz_load(); return scroll

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
        add_grp.setStyleSheet(self._accent_btn()); add_grp.clicked.connect(self._add_group)
        del_grp = QPushButton("Delete Selected"); del_grp.setFixedHeight(32)
        del_grp.setCursor(Qt.CursorShape.PointingHandCursor)
        del_grp.setStyleSheet(f"QPushButton{{background:{RED_LIGHT};color:{RED};border:none;border-radius:16px;font-size:11px;padding:0 12px;}}QPushButton:hover{{background:{RED};color:white;}}")
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
        recalc_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER_DARK};border:1px solid {AMBER};"
            f"border-radius:17px;font-size:11px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{AMBER_LIGHTEST};}}"
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
        disc_save = QPushButton("💾  Save Groups & Discounts"); disc_save.setFixedHeight(38)
        disc_save.setStyleSheet(self._accent_btn())
        disc_save.clicked.connect(self._groups_disc_save)
        lay.addWidget(disc_save)
        scroll.setWidget(fw); return scroll

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

    def _build_printers_panel(self):
        """Printer settings sub-tab — a single receipt printer, its print
        mode, and the paper width that drives column formatting."""
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(fw); lay.setContentsMargins(20,20,20,20); lay.setSpacing(14)

        lay.addWidget(self._section_lbl("Printer Configuration"))
        lay.addWidget(self._hdiv())

        def ps_row(label, widget, hint_txt=""):
            box = QFrame(); box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
            bl = QVBoxLayout(box); bl.setContentsMargins(14,10,14,10); bl.setSpacing(6)
            lbl = QLabel(label); lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
            bl.addWidget(lbl); bl.addWidget(widget)
            if hint_txt:
                h = QLabel(hint_txt); h.setStyleSheet(f"color:{MUTED};font-size:10px;"); h.setWordWrap(True); bl.addWidget(h)
            return box

        # ── Receipt printer ───────────────────────────────────────────
        self.ps_receipt_combo = QComboBox()
        self.ps_receipt_combo.setFixedHeight(34)
        self.ps_receipt_combo.setEditable(True)
        self.ps_receipt_combo.setStyleSheet(f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:13px;}}QComboBox:focus{{border-color:{AMBER};}}")
        self.ps_receipt_combo.lineEdit().setPlaceholderText("Leave blank to use OS default printer…")

        refresh_receipt = QPushButton("↻")
        refresh_receipt.setFixedSize(34, 34)
        refresh_receipt.setToolTip("Refresh printer list")
        refresh_receipt.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_receipt.setStyleSheet(f"QPushButton{{background:transparent;color:{AMBER};border:1.5px solid {AMBER};border-radius:17px;font-size:14px;font-weight:700;}}QPushButton:hover{{background:{AMBER};color:white;}}")
        refresh_receipt.clicked.connect(lambda: self._printers_refresh_list(self.ps_receipt_combo))

        receipt_box = QFrame()
        receipt_box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        rb = QVBoxLayout(receipt_box); rb.setContentsMargins(14,10,14,10); rb.setSpacing(6)
        rb_lbl = QLabel("Receipt Printer")
        rb_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
        rb.addWidget(rb_lbl)
        rb_row = QHBoxLayout(); rb_row.setSpacing(8)
        rb_row.addWidget(self.ps_receipt_combo, stretch=1)
        rb_row.addWidget(refresh_receipt)
        rb.addLayout(rb_row)
        rb_hint = QLabel(
            "Used for every receipt, void, refund, and session print.  "
            "Leave blank to use your OS default printer — no configuration needed."
        )
        rb_hint.setStyleSheet(f"color:{MUTED};font-size:10px;"); rb_hint.setWordWrap(True)
        rb.addWidget(rb_hint)

        # ── Print mode ────────────────────────────────────────────────
        self.ps_mode_combo = QComboBox()
        self.ps_mode_combo.setFixedHeight(34)
        self.ps_mode_combo.setStyleSheet(f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:13px;}}QComboBox:focus{{border-color:{AMBER};}}")
        self.ps_mode_combo.addItem("Raw Text (dot matrix / thermal)", "raw")
        self.ps_mode_combo.addItem("Raster / Graphics (normal printer)", "raster")
        mode_hint = (
            "Raw Text sends plain text straight to the printer — required for "
            "dot matrix printers like the TM-U220 on a generic text-only driver. "
            "Raster renders through the OS driver like a normal document; use it "
            "for printers that don't accept raw text passthrough."
        )

        # ── Paper width ───────────────────────────────────────────────
        self.ps_width_combo = QComboBox()
        self.ps_width_combo.setFixedHeight(34)
        self.ps_width_combo.setStyleSheet(f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:13px;}}QComboBox:focus{{border-color:{AMBER};}}")
        from utils.printer_capabilities import STANDARD_WIDTHS_MM, columns_for_width_mm
        self._ps_width_labels = {}
        for mm in STANDARD_WIDTHS_MM:
            cols = columns_for_width_mm(mm)
            label = f"{mm}mm  ({cols} columns)"
            self._ps_width_labels[mm] = label
            self.ps_width_combo.addItem(label, mm)

        detect_btn = QPushButton("Auto-Detect")
        detect_btn.setFixedHeight(34)
        detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        detect_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{AMBER};border:1.5px solid {AMBER};border-radius:7px;padding:0 12px;font-size:12px;font-weight:600;}}QPushButton:hover{{background:{AMBER};color:white;}}")
        detect_btn.clicked.connect(self._printers_detect_width)

        width_box = QFrame()
        width_box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        wb = QVBoxLayout(width_box); wb.setContentsMargins(14,10,14,10); wb.setSpacing(6)
        wb_lbl = QLabel("Paper Width")
        wb_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
        wb.addWidget(wb_lbl)
        wb_row = QHBoxLayout(); wb_row.setSpacing(8)
        wb_row.addWidget(self.ps_width_combo, stretch=1)
        wb_row.addWidget(detect_btn)
        wb.addLayout(wb_row)
        wb_hint = QLabel(
            "Sets how many characters fit per line on receipts, voids, refunds, "
            "and session reports. Auto-Detect reads the width from the printer "
            "driver — it only works reliably if the driver is correctly "
            "configured for the installed roll, so check the result and adjust "
            "manually if needed."
        )
        wb_hint.setStyleSheet(f"color:{MUTED};font-size:10px;"); wb_hint.setWordWrap(True)
        wb.addWidget(wb_hint)

        # ── Copies ────────────────────────────────────────────────────
        self.ps_copies = QSpinBox(); self.ps_copies.setRange(1,5); self.ps_copies.setValue(1)
        self.ps_copies.setFixedHeight(34); self.ps_copies.setFixedWidth(100)
        self.ps_copies.setStyleSheet(f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;padding:0 10px;font-size:13px;}}QSpinBox:focus{{border-color:{AMBER};}}")

        # ── ESC/POS ───────────────────────────────────────────────────
        self.ps_escpos = QCheckBox("Send real ESC/POS commands (bold headers/totals, real paper cut)")
        self.ps_escpos.setStyleSheet(
            f"QCheckBox{{color:{DARK_CARD};font-size:12px;font-weight:500;}}"
            f"QCheckBox::indicator{{width:16px;height:16px;border:1px solid {BORDER};border-radius:3px;}}"
            f"QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}"
        )
        self.ps_cash_drawer = QCheckBox("Open cash drawer on cash/split-tender sales")
        self.ps_cash_drawer.setStyleSheet(self.ps_escpos.styleSheet())

        escpos_box = QFrame()
        escpos_box.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        eb = QVBoxLayout(escpos_box); eb.setContentsMargins(14,10,14,10); eb.setSpacing(8)
        eb_lbl = QLabel("ESC/POS Commands")
        eb_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
        eb.addWidget(eb_lbl)
        eb.addWidget(self.ps_escpos)
        eb.addWidget(self.ps_cash_drawer)
        eb_hint = QLabel(
            "Raw Text mode only. Needs a printer whose firmware understands ESC/POS "
            "(e.g. TM-U220) — it degrades to plain text automatically if the "
            "python-escpos library isn't installed. The drawer must be wired "
            "through the receipt printer for the kick to work."
        )
        eb_hint.setStyleSheet(f"color:{MUTED};font-size:10px;"); eb_hint.setWordWrap(True)
        eb.addWidget(eb_hint)

        def _sync_escpos_enabled():
            raw = self.ps_mode_combo.currentData() != "raster"
            self.ps_escpos.setEnabled(raw)
            self.ps_cash_drawer.setEnabled(raw and self.ps_escpos.isChecked())
        self.ps_mode_combo.currentIndexChanged.connect(_sync_escpos_enabled)
        self.ps_escpos.toggled.connect(_sync_escpos_enabled)
        self._sync_escpos_enabled = _sync_escpos_enabled

        # ── Label printer ─────────────────────────────────────────────
        self.ps_label = self._finp("e.g. Zebra_GK420d")

        # ── Layout ────────────────────────────────────────────────────
        lay.addWidget(receipt_box)
        lay.addWidget(ps_row("Print Mode", self.ps_mode_combo, mode_hint))
        lay.addWidget(width_box)
        lay.addWidget(escpos_box)
        copies_lbl = QLabel("Receipt Copies")
        copies_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;")
        copies_row = QHBoxLayout(); copies_row.addWidget(self.ps_copies); copies_row.addStretch()
        lay.addWidget(copies_lbl); lay.addLayout(copies_row)
        lay.addWidget(ps_row("Label Printer", self.ps_label, "Used for shelf price labels"))

        lay.addStretch()
        self.printers_feedback = QLabel("")
        self.printers_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        self.printers_feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.printers_feedback)

        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        test_btn = QPushButton("🖨  Test Print"); test_btn.setFixedHeight(38)
        test_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER};border:1.5px solid {AMBER};"
            f"border-radius:8px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{AMBER};color:white;}}"
        )
        test_btn.clicked.connect(self._printers_test)
        save_btn = QPushButton("💾  Save Printer Settings"); save_btn.setFixedHeight(38)
        save_btn.setStyleSheet(self._accent_btn()); save_btn.clicked.connect(self._printers_save)
        btn_row.addWidget(test_btn); btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        self._printers_load()
        scroll.setWidget(fw); return scroll

    def _printers_refresh_list(self, combo: "QComboBox"):
        """Populate a printer combo with the current OS printer list."""
        try:
            from PyQt6.QtPrintSupport import QPrinterInfo
            current = combo.currentText().strip()
            combo.clear()
            combo.addItem("")   # blank = OS default
            for info in QPrinterInfo.availablePrinters():
                combo.addItem(info.printerName())
            if current:
                idx = combo.findText(current)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                if idx < 0:
                    combo.setEditText(current)
            self.printers_feedback.setText(
                f"✓  Found {combo.count() - 1} printer(s).")
            self.printers_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        except Exception as e:
            self.printers_feedback.setText(f"Could not list printers: {e}")
            self.printers_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")

    def _printers_select_width(self, width_mm: int):
        """Select the closest standard width entry in the paper-width combo."""
        from utils.printer_capabilities import STANDARD_WIDTHS_MM
        closest = min(STANDARD_WIDTHS_MM, key=lambda mm: abs(mm - width_mm))
        idx = self.ps_width_combo.findData(closest)
        if idx >= 0:
            self.ps_width_combo.setCurrentIndex(idx)

    def _printers_detect_width(self):
        """Query the printer driver for its configured paper width."""
        from utils.printer_capabilities import detect_paper_width_mm
        name = self.ps_receipt_combo.currentText().strip()
        detected = detect_paper_width_mm(name)
        if detected:
            self._printers_select_width(detected)
            self.printers_feedback.setText(f"✓  Detected {detected}mm from the printer driver.")
            self.printers_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        else:
            self.printers_feedback.setText(
                "Could not detect paper width from the driver — set it manually.")
            self.printers_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")

    def _printers_load(self):
        from core.db_config import get
        self.ps_copies.setValue(int(get("receipt_copies", "1") or "1"))
        self.ps_label.setText(get("label_printer_name", ""))
        self._printers_refresh_list(self.ps_receipt_combo)

        saved = get("receipt_printer_name", "")
        if saved:
            idx = self.ps_receipt_combo.findText(saved)
            if idx >= 0:
                self.ps_receipt_combo.setCurrentIndex(idx)
            else:
                self.ps_receipt_combo.setEditText(saved)

        saved_mode = get("receipt_printer_mode", "raw")
        idx = self.ps_mode_combo.findData(saved_mode)
        self.ps_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)

        saved_width = int(get("receipt_paper_width_mm", "76") or "76")
        self._printers_select_width(saved_width)

        self.ps_escpos.setChecked(get("receipt_printer_escpos", "0").strip() == "1")
        self.ps_cash_drawer.setChecked(get("cash_drawer_kick_on_cash_sale", "0").strip() == "1")
        self._sync_escpos_enabled()

    def _printers_save(self):
        try:
            from core.db_config import set_many
            set_many({
                "receipt_printer_name":   self.ps_receipt_combo.currentText().strip(),
                "receipt_printer_mode":   self.ps_mode_combo.currentData(),
                "receipt_paper_width_mm": str(self.ps_width_combo.currentData()),
                "label_printer_name":     self.ps_label.text().strip(),
                "receipt_copies":         str(self.ps_copies.value()),
                "receipt_printer_escpos": "1" if self.ps_escpos.isChecked() else "0",
                "cash_drawer_kick_on_cash_sale": "1" if self.ps_cash_drawer.isChecked() else "0",
            })
            self.printers_feedback.setText("✓  Printer settings saved.")
            self.printers_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        except Exception as e:
            self.printers_feedback.setText(str(e))
            self.printers_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")

    def _printers_test(self):
        """Send a test print to the receipt printer, using the selected
        mode — real ESC/POS bytes (bold banner, cut, optional drawer kick)
        if enabled, otherwise plain text."""
        from utils.thermal_printer import ThermalPrinter, PrinterError
        name = self.ps_receipt_combo.currentText().strip()
        mode = self.ps_mode_combo.currentData()
        width = self.ps_width_combo.currentData() or 76
        use_escpos = mode != "raster" and self.ps_escpos.isChecked()
        kick_drawer = use_escpos and self.ps_cash_drawer.isChecked()
        from utils.printer_capabilities import columns_for_width_mm
        cols = columns_for_width_mm(width)
        self.printers_feedback.setText("Sending test print…")
        self.printers_feedback.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        div = "-" * cols
        lines = [
            ("MERCHANT POS SYSTEMS", "biz_name"),
            ("** TEST PRINT **", "title"),
            (div, "div"),
            ("Printer connected successfully", "normal"),
            (f"Printer: {name or 'OS Default'}", "normal"),
            (f"Mode: {'Raw Text' if mode != 'raster' else 'Raster'}", "normal"),
            (f"ESC/POS: {'On' if use_escpos else 'Off'}", "normal"),
            (f"Width: {width}mm ({cols} cols)", "normal"),
            (div, "div"),
        ]
        test_text = "\n" + "\n".join(t for t, _k in lines) + "\n\n\n\n"
        try:
            printer = ThermalPrinter(name, copies=1, mode=mode)
            data = None
            if use_escpos:
                from utils.escpos_builder import build_escpos_bytes
                data = build_escpos_bytes(lines, cut=True, cash_drawer=kick_drawer)
            with printer as p:
                if data is not None:
                    p.print_bytes(data)
                else:
                    p.print_text(test_text)
            self.printers_feedback.setText("✓  Test print sent successfully.")
            self.printers_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        except PrinterError as e:
            self.printers_feedback.setText(f"✗  {str(e).splitlines()[0]}")
            self.printers_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Printer Test Failed", str(e))
        except Exception as e:
            self.printers_feedback.setText(f"✗  {e}")
            self.printers_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")

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

        self.pg_enabled = QCheckBox("Enable PostgreSQL sync")
        self.pg_enabled.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:500;")
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


    def _biz_load(self):
        b = get_business()
        self.biz_name.setText(b.get("name",""))
        self.biz_address.setText(b.get("address",""))
        self.biz_phone.setText(b.get("phone",""))
        self.biz_email.setText(b.get("email",""))
        self.biz_tax_id.setText(b.get("tax_id",""))
        self.biz_footer.setText(b.get("receipt_footer",""))
        from core.db_config import gct_rate as gr, get_bool, get_int
        self.biz_gct.setValue(gr() * 100)
        self.perm_require_remove_auth.setChecked(get_bool("require_remove_auth", False))
        self.perm_session_gate.setChecked(get_bool("session_gate", False))
        self.perm_cart_qty_edit.setChecked(get_bool("allow_cart_qty_edit", False))
        low_stock = get_bool("low_stock_warning", False)
        self.perm_low_stock.setChecked(low_stock)
        self.perm_low_stock_threshold.setValue(get_int("low_stock_threshold", 5))
        self.perm_low_stock_threshold.setEnabled(low_stock)
        self.perm_stock_tracking.setChecked(get_bool("stock_tracking", False))

    def _biz_save(self):
        try:
            update_business(name=self.biz_name.text().strip(),
                            address=self.biz_address.text().strip(),
                            phone=self.biz_phone.text().strip(),
                            email=self.biz_email.text().strip(),
                            tax_id=self.biz_tax_id.text().strip(),
                            receipt_footer=self.biz_footer.text().strip())
            cfg_set("gct_rate", str(self.biz_gct.value() / 100))
            cfg_set("require_remove_auth", "1" if self.perm_require_remove_auth.isChecked() else "0")
            cfg_set("session_gate",        "1" if self.perm_session_gate.isChecked()         else "0")
            cfg_set("allow_cart_qty_edit",  "1" if self.perm_cart_qty_edit.isChecked()       else "0")
            cfg_set("low_stock_warning",    "1" if self.perm_low_stock.isChecked()            else "0")
            cfg_set("low_stock_threshold",  str(self.perm_low_stock_threshold.value()))
            cfg_set("stock_tracking",       "1" if self.perm_stock_tracking.isChecked()       else "0")
            self._save_discount_levels()
            self.biz_feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
            self.biz_feedback.setText("✓  Business info saved.")
        except Exception as e:
            self.biz_feedback.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")
            self.biz_feedback.setText(str(e))

    def _load_discount_levels(self):
        try:
            import sqlite3; from config import DB_PRODUCTS
            con = sqlite3.connect(DB_PRODUCTS)
            rows = con.execute("SELECT discount_percent, min_quantity FROM discount_levels ORDER BY min_quantity LIMIT 2").fetchall()
            con.close()
            for i, (pct, qty) in enumerate(rows):
                if i < len(self._disc_rows):
                    self._disc_rows[i][0].setValue(pct)
                    self._disc_rows[i][1].setValue(qty)
        except Exception: pass

    def _save_discount_levels(self):
        try:
            import sqlite3; from config import DB_PRODUCTS
            con = sqlite3.connect(DB_PRODUCTS)
            rows = con.execute("SELECT id FROM discount_levels ORDER BY min_quantity LIMIT 2").fetchall()
            for i, (did,) in enumerate(rows):
                if i < len(self._disc_rows):
                    pct = self._disc_rows[i][0].value()
                    qty = self._disc_rows[i][1].value()
                    con.execute("UPDATE discount_levels SET discount_percent=?, min_quantity=? WHERE id=?", (pct, qty, did))
            con.commit(); con.close()
        except Exception: pass

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

    def _add_group(self):
        name = self.new_group_inp.text().strip()
        if not name: return
        try: add_group(name); self.new_group_inp.clear(); self._load_groups()
        except Exception as e: QMessageBox.warning(self, "Error", str(e))

    def _delete_group(self):
        row = self.groups_table.currentRow()
        item = self.groups_table.item(row, 0)
        if not item: return
        gid = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Delete Group", f"Delete group '{item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_group(gid); self._load_groups()



    def _build_dbf_import_tab(self):
        from ui.manager.dbf_import_tab import DBFImportTab
        tab = DBFImportTab(self.user, parent=self)
        tab.import_complete.connect(self._on_import_complete)
        return tab

    def _on_import_complete(self):
        """Refresh groups and discount combos in the Products form after a DBF import."""
        self._populate_groups()
        self._populate_discount_levels(self.f_disc1)
        self._populate_discount_levels(self.f_disc2)

    def _build_quickkeys_tab(self):
        w = QWidget(); w.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(10)
        hint = QLabel("Assign a product to each F-key (F1–F8). Start typing a product name to search — select from the results.")
        hint.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;"); lay.addWidget(hint)

        all_prods = [(p["id"], p["name"], p["selling_price"]) for p in get_products(limit=5000)]
        self._qk_widgets = []
        for k in get_quick_keys():
            row = QHBoxLayout(); row.setSpacing(10)
            badge = QLabel(f"F{k['slot']}"); badge.setFixedSize(40,32)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"background:{DARK_CARD};color:{AMBER};border-radius:6px;font-size:11px;font-weight:700;")
            sw = ProductSearchWidget(); sw.set_products(all_prods)
            if k.get("product_id") and k.get("product_name"):
                sw.set_selection(k["product_id"], f"{k['product_name']}  (${k['product_price']:.2f})")
            sw.setProperty("slot", k["slot"])
            row.addWidget(badge); row.addWidget(sw, stretch=1)
            lay.addLayout(row); self._qk_widgets.append(sw)

        lay.addStretch()
        save_btn = QPushButton("💾  Save Quick Keys"); save_btn.setFixedHeight(42)
        save_btn.setStyleSheet(self._accent_btn()); save_btn.clicked.connect(self._qk_save_manager)
        lay.addWidget(save_btn); return w

    def _qk_save_manager(self):
        assignments = []
        for sw in self._qk_widgets:
            slot = sw.property("slot"); pid = sw.currentData()
            if pid:
                p = get_product_by_id(pid)
                assignments.append({"slot":slot,"product_id":pid,
                                     "product_name":p["name"] if p else "",
                                     "product_price":p["selling_price"] if p else 0})
            else:
                assignments.append({"slot":slot,"product_id":None,"product_name":None,"product_price":None})
        save_quick_keys(assignments)
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
            f"border-radius:7px;padding:0 10px;font-size:12px;}}"
            f"QLineEdit:focus{{border-color:{AMBER};background:#fffef9;}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
        )

    def _combo_style(self):
        return (
            f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
            f"QComboBox QAbstractItemView{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};outline:none;"
            f"selection-background-color:{AMBER};selection-color:white;}}"
        )

    def _accent_btn(self):
        return f"QPushButton{{background:{AMBER};color:white;border:none;border-radius:17px;font-size:12px;font-weight:600;padding:0 16px;}}QPushButton:hover{{background:{AMBER_DARK};}}"

    def _finp(self, placeholder, uppercase=True):
        if uppercase:
            inp = self.make_upper_input(placeholder)
        else:
            inp = QLineEdit(); inp.setPlaceholderText(placeholder); inp.setFixedHeight(34)
        inp.setStyleSheet(self._input_style()); return inp

    def _flabel(self, text):
        l = QLabel(text); l.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;"); return l

    def _section_lbl(self, text):
        l = QLabel(text.upper()); l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;"); return l

    def _hdiv(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;"); return f
