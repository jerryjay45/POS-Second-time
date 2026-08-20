"""
ui/cashier/cashier_window.py
Cashier dashboard — adapted from prototype layout and functions,
recolored to amber/dark theme.

Layout:
  Topbar | [F1-F8 sidebar] | [Center: qty+search, results list, cart table, bottom btns] | [Right: cart nav, last change, totals]
"""

from PyQt6.QtWidgets import (  # cashier_window

    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem,
    QSpinBox, QMessageBox, QDialog,
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui  import QColor, QKeySequence

from ui.base_window   import BaseWindow
from ui.shared.theme  import (
    AMBER, AMBER_DARK, AMBER_LIGHT, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_3, DARK_4, DARK_CARD,
    WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN,
)
from core.db_users    import open_session, add_session_sales, get_open_session
from core.db_config   import get_quick_keys, gct_rate, get_bool
from core.db_products import get_product_by_barcode, get_products, get_product_by_id
from core.db_config   import get_quick_keys, gct_rate, get_business
from PyQt6.QtCore import pyqtSignal


# Cart panel colors — change per active cart
CART_COLORS = ["#EF9F27", "#1a9e6c", "#c7622a"]


class CashierWindow(BaseWindow):
    logout_requested = pyqtSignal()

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user          = user
        self._gct_rate     = gct_rate()
        self._quick_keys   = self._load_quick_keys()
        self._disc_rules   = self._load_discount_rules()
        self._last_txn_id  = None

        # Manager-controlled feature flags (read once at login)
        from core.db_config import get_bool, get_int
        self._allow_qty_edit      = get_bool("allow_cart_qty_edit", False)
        self._low_stock_warning   = get_bool("low_stock_warning",   False)
        self._low_stock_threshold = get_int("low_stock_threshold",  5)
        self._session_gate        = get_bool("session_gate",        False)

        # Resume existing open session or create a new one
        # (if session_gate is on, login_window already blocked cashiers without a session)
        existing = get_open_session(user["id"])
        if existing:
            self._session_id  = existing["id"]
            self._resuming    = True
        else:
            self._session_id  = open_session(user["id"])
            self._resuming    = False

        self._session_closing = False   # set True when supervisor closes session

        # 3 independent carts
        self.carts       = [[] for _ in range(3)]
        self.active_cart = 0

        self.setWindowTitle("POS System — Cashier")
        self.setMinimumSize(1280, 720)
        self._build_ui()
        self._start_clock()
        self._show_session_started_popup()

        # Listen for supervisor session broadcasts
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if hasattr(app, "session_closed"):
            app.session_closed.connect(self._on_session_closed_by_supervisor)
        if hasattr(app, "session_opened"):
            app.session_opened.connect(self._on_session_opened_by_supervisor)

    # ── Property: active cart list ────────────────────────────────────
    @property
    def cart(self):
        return self.carts[self.active_cart]

    # ================================================================
    # UI BUILD
    # ================================================================

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background:{WARM_WHITE};")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_fkey_panel())
        body.addWidget(self._build_center_panel(), stretch=1)
        body.addWidget(self._build_right_panel())
        lay.addLayout(body, stretch=1)

    # ── Topbar ────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{DARK};border-bottom:1px solid {DARK_4};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)

        left = QLabel(f"POS System  |  Cashier:  {self.user['full_name']}")
        left.setStyleSheet(f"color:white;font-size:13px;font-weight:600;")

        self._clock_lbl = QLabel()
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clock_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-family:'DM Mono',monospace;")

        logout = QPushButton("Logout  ↗")
        logout.setFixedHeight(30)
        logout.setCursor(Qt.CursorShape.PointingHandCursor)
        logout.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:white;border:none;
            border-radius:15px;font-size:11px;font-weight:700;padding:0 16px;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        logout.clicked.connect(self._handle_logout)

        lay.addWidget(left)
        lay.addStretch()
        lay.addWidget(self._clock_lbl)
        lay.addStretch()
        lay.addWidget(logout)
        return bar

    # ── F-key sidebar ─────────────────────────────────────────────────
    def _build_fkey_panel(self):
        panel = QFrame()
        panel.setFixedWidth(110)
        panel.setStyleSheet(f"background:{DARK_2};border-right:1px solid {DARK_4};")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 10, 6, 10)
        lay.setSpacing(5)

        self._fkey_btns = []
        for i in range(8):
            btn = QPushButton()
            btn.setMinimumHeight(52)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            qk = self._quick_keys[i] if i < len(self._quick_keys) else None
            if qk and qk.get("product_id"):
                btn.setText(f"F{i+1}\n{qk['product_name'][:12]}\n${qk['product_price']:.2f}")
                btn.setStyleSheet(self._fkey_style(True))
                btn.clicked.connect(lambda _, idx=i: self._add_quick_key(idx))
            else:
                btn.setText(f"F{i+1}\n—")
                btn.setEnabled(False)
                btn.setStyleSheet(self._fkey_style(False))
            self._fkey_btns.append(btn)
            lay.addWidget(btn)
        lay.addStretch()
        return panel

    # ── Center panel ──────────────────────────────────────────────────
    def _build_center_panel(self):
        panel = QFrame()
        panel.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Input bar
        input_bar = QFrame()
        input_bar.setFixedHeight(50)
        input_bar.setStyleSheet(f"background:{WARM_WHITE};border-bottom:1px solid {BORDER};")
        input_lay = QHBoxLayout(input_bar)
        input_lay.setContentsMargins(10, 8, 10, 8)
        input_lay.setSpacing(8)

        qty_lbl = QLabel("Qty:")
        qty_lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;")

        self.qty_spinbox = QSpinBox()
        self.qty_spinbox.setMinimum(1)
        self.qty_spinbox.setMaximum(9999)
        self.qty_spinbox.setValue(1)
        self.qty_spinbox.setFixedWidth(64)
        self.qty_spinbox.setFixedHeight(32)
        self.qty_spinbox.setStyleSheet(f"""
            QSpinBox{{background:white;color:{DARK_CARD};
            border:2px solid {AMBER};border-radius:6px;
            padding:0 6px;font-size:13px;}}
            QSpinBox:focus{{border-color:{AMBER_DARK};}}
            QSpinBox::up-button,QSpinBox::down-button{{width:16px;background:{DARK_2};border:none;}}
        """)

        # Enter in qty → jump to search
        def _qty_enter(event):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.search_input.setFocus()
                self.search_input.selectAll()
            else:
                QSpinBox.keyPressEvent(self.qty_spinbox, event)
        self.qty_spinbox.keyPressEvent = _qty_enter

        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(34)
        self.search_input.setPlaceholderText("↵  Barcode  |  Search  ↵  Checkout")
        self.search_input.setStyleSheet(f"""
            QLineEdit{{background:white;color:{DARK_CARD};
            border:2px solid #888;border-radius:17px;
            padding:0 16px;font-size:13px;}}
            QLineEdit:focus{{border-color:{AMBER};}}
        """)
        self.search_input.returnPressed.connect(self._handle_search_enter)
        self.search_input.keyPressEvent = self._search_key_press

        checkout_btn = QPushButton("Checkout")
        checkout_btn.setFixedSize(110, 34)
        checkout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        checkout_btn.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:white;border:none;
            border-radius:17px;font-size:12px;font-weight:600;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        checkout_btn.clicked.connect(self._handle_checkout)

        input_lay.addWidget(qty_lbl)
        input_lay.addWidget(self.qty_spinbox)
        input_lay.addWidget(self.search_input, stretch=1)
        input_lay.addWidget(checkout_btn)
        lay.addWidget(input_bar)

        # Match-count label (styled like the price tag tab's search feedback)
        self.match_lbl = QLabel("")
        self.match_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;padding:2px 4px 0 4px;")
        self.match_lbl.setVisible(False)
        lay.addWidget(self.match_lbl)

        # Search results list (inline, hidden by default)
        self.results_list = QListWidget()
        self.results_list.setVisible(False)
        self.results_list.setMinimumHeight(100)
        self.results_list.setMaximumHeight(200)
        self.results_list.setStyleSheet(f"""
            QListWidget{{background:{WHITE};color:{DARK_CARD};
            border:1px solid {BORDER};border-radius:8px;font-size:13px;}}
            QListWidget::item{{padding:8px 14px;border-bottom:1px solid {BORDER_LIGHT};}}
            QListWidget::item:selected{{background:{AMBER};color:white;}}
            QListWidget::item:hover{{background:{AMBER_LIGHTEST};}}
        """)
        self.results_list.itemClicked.connect(self._add_from_results)
        self.results_list.keyPressEvent = self._results_key_press
        lay.addWidget(self.results_list)

        # Cart table
        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(7)
        self.cart_table.setHorizontalHeaderLabels([
            "Product", "Qty", "Price", "Discount",
            f"GCT ({self._gct_rate*100:.0f}%)", "Total", "Remove"
        ])
        hh = self.cart_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in enumerate([70, 90, 90, 90, 90, 60], start=1):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.cart_table.setColumnWidth(col, w)
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setShowGrid(False)
        self.cart_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cart_table.cellDoubleClicked.connect(self._on_cart_double_click)
        self.cart_table.setStyleSheet(f"""
            QTableWidget{{background:{WHITE};border:none;font-size:12px;}}
            QTableWidget::item{{padding:6px 8px;border-bottom:1px solid {BORDER_LIGHT};color:{DARK_CARD};}}
            QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}
            QHeaderView::section{{background:{DARK};color:{AMBER};font-size:11px;
            font-weight:700;padding:7px 8px;border:none;border-right:1px solid {DARK_4};}}
        """)
        lay.addWidget(self.cart_table, stretch=1)

        # Bottom buttons
        bot = QFrame()
        bot.setFixedHeight(46)
        bot.setStyleSheet(f"background:{DARK_2};border-top:1px solid {DARK_4};")
        bot_lay = QHBoxLayout(bot)
        bot_lay.setContentsMargins(10, 7, 10, 7)
        bot_lay.setSpacing(8)

        clear_btn = QPushButton("🗑  Clear Cart")
        clear_btn.setFixedHeight(30)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(self._pill_btn_style())
        clear_btn.clicked.connect(self._clear_cart)

        misc_btn = QPushButton("✱  Misc Item")
        misc_btn.setFixedHeight(30)
        misc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        misc_btn.setStyleSheet(self._pill_btn_style())
        misc_btn.clicked.connect(self._add_misc_item)

        price_btn = QPushButton("▦  Price Check")
        price_btn.setFixedHeight(30)
        price_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        price_btn.setStyleSheet(self._pill_btn_style())
        price_btn.clicked.connect(self._price_check)

        bot_lay.addWidget(clear_btn)
        bot_lay.addWidget(misc_btn)

        remove_btn = QPushButton("⊘  Remove Items")
        remove_btn.setFixedHeight(30)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(f"""
            QPushButton{{background:{DARK_4};color:#ef4444;
            border:1px solid #7a1e1e;border-radius:15px;
            font-size:11px;font-weight:600;padding:0 14px;}}
            QPushButton:hover{{background:#7a1e1e;color:white;}}
        """)
        remove_btn.clicked.connect(self._handle_void)
        bot_lay.addWidget(remove_btn)
        bot_lay.addWidget(price_btn)
        bot_lay.addStretch()
        lay.addWidget(bot)

        return panel

    # ── Right panel ───────────────────────────────────────────────────
    def _build_right_panel(self):
        panel = QFrame()
        panel.setFixedWidth(168)
        panel.setStyleSheet(f"background:{DARK_2};border-left:1px solid {DARK_4};")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Cart selector
        self._cart_section = QFrame()
        self._cart_section.setStyleSheet(f"background:{CART_COLORS[0]};border:none;")
        cs_lay = QVBoxLayout(self._cart_section)
        cs_lay.setContentsMargins(10, 10, 10, 10)
        cs_lay.setSpacing(6)

        self._cart_lbl = QLabel("Cart 1")
        self._cart_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cart_lbl.setStyleSheet("color:white;font-size:16px;font-weight:700;background:transparent;")

        self._cart_items_lbl = QLabel("")
        self._cart_items_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cart_items_lbl.setStyleSheet("color:rgba(255,255,255,0.75);font-size:11px;font-weight:400;background:transparent;")

        nav_row = QHBoxLayout()
        prev_btn = QPushButton("←"); prev_btn.setFixedSize(34,34)
        prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        prev_btn.setStyleSheet(self._nav_btn_style())
        prev_btn.clicked.connect(self._prev_cart)
        next_btn = QPushButton("→"); next_btn.setFixedSize(34,34)
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setStyleSheet(self._nav_btn_style())
        next_btn.clicked.connect(self._next_cart)
        nav_row.addWidget(prev_btn); nav_row.addStretch(); nav_row.addWidget(next_btn)

        cs_lay.addWidget(self._cart_lbl)
        cs_lay.addWidget(self._cart_items_lbl)
        cs_lay.addLayout(nav_row)
        lay.addWidget(self._cart_section)

        # Reprint last receipt button (hidden until first txn)
        self._reprint_btn = QPushButton("🖨  Reprint Last")
        self._reprint_btn.setFixedHeight(30)
        self._reprint_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reprint_btn.setStyleSheet(f"""
            QPushButton{{background:{DARK_3};color:{MUTED};
            border:1px solid {DARK_4};border-radius:5px;
            font-size:10px;font-weight:600;margin:6px 8px 0 8px;}}
            QPushButton:hover{{background:{DARK_4};color:white;}}
            QPushButton:pressed{{background:{AMBER};color:white;}}
        """)
        self._reprint_btn.setVisible(False)
        self._reprint_btn.clicked.connect(self._reprint_last)
        lay.addWidget(self._reprint_btn)

        # Last change display (hidden until first txn)
        self._change_frame = QFrame()
        self._change_frame.setStyleSheet(f"background:{DARK_2};border:none;")
        cf_lay = QVBoxLayout(self._change_frame)
        cf_lay.setContentsMargins(10, 10, 10, 8)
        cf_lay.setSpacing(3)
        _line = QFrame(); _line.setFrameShape(QFrame.Shape.HLine)
        _line.setStyleSheet("background:rgba(255,255,255,0.08);max-height:1px;border:none;")
        _title = QLabel("LAST CHANGE")
        _title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _title.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;background:transparent;")
        self._change_display = QLabel("")
        self._change_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._change_display.setStyleSheet(f"color:{GREEN};font-size:22px;font-weight:800;background:transparent;")
        cf_lay.addWidget(_line); cf_lay.addWidget(_title); cf_lay.addWidget(self._change_display)
        self._change_frame.setVisible(False)
        lay.addWidget(self._change_frame)

        # Totals blocks
        def block(title, attr, big=False):
            f = QFrame()
            color = CART_COLORS[self.active_cart]
            f.setStyleSheet(f"background:{color};border:none;")
            bl = QVBoxLayout(f); bl.setContentsMargins(8,8,8,8); bl.setSpacing(3)
            line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet("background:rgba(255,255,255,0.15);max-height:1px;border:none;")
            t = QLabel(title); t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet(f"color:#e2e8f0;font-size:{'14' if big else '12'}px;background:transparent;")
            v = QLabel("$0.00"); v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.setStyleSheet(f"color:white;font-size:{'22' if big else '14'}px;"
                           f"font-weight:{'800' if big else '500'};background:transparent;")
            bl.addWidget(line); bl.addWidget(t); bl.addWidget(v)
            setattr(self, attr, v)
            setattr(self, f"{attr}_frame", f)
            return f

        lay.addStretch()
        lay.addWidget(block("Subtotal",                           "subtotal_label"))
        lay.addWidget(block(f"GCT ({self._gct_rate*100:.2f}%)",  "gct_label"))
        lay.addWidget(block("Discount",                           "discount_label"))
        lay.addWidget(block("TOTAL",                              "total_label", big=True))
        return panel

    # ================================================================
    # CLOCK
    # ================================================================

    def _show_session_started_popup(self):
        """Brief non-blocking popup informing cashier a session has started."""
        from PyQt6.QtWidgets import QFrame, QLabel, QHBoxLayout
        from PyQt6.QtCore    import QTimer, QDateTime

        popup = QFrame(self)
        popup.setObjectName("sessionPopup")
        popup.setStyleSheet(f"""
            QFrame#sessionPopup {{
                background: {DARK_2};
                border: 1px solid {AMBER};
                border-radius: 10px;
            }}
        """)
        popup.setFixedSize(340, 64)

        pl = QHBoxLayout(popup)
        pl.setContentsMargins(16, 0, 16, 0)

        icon = QLabel("▶")
        icon.setStyleSheet(f"color:{AMBER};font-size:18px;background:transparent;")

        now    = QDateTime.currentDateTime().toString("dd MMM yyyy  hh:mm AP")
        action = "resumed" if self._resuming else "started"
        msg = QLabel(f"Session #{self._session_id:04d} {action}  ·  {now}")
        msg.setStyleSheet(f"color:white;font-size:12px;font-weight:500;background:transparent;")

        pl.addWidget(icon); pl.addWidget(msg, stretch=1)

        # Position top-right of window
        popup.move(self.width() - popup.width() - 20, 56)
        popup.show(); popup.raise_()

        # Auto-dismiss after 4 seconds with fade
        def _dismiss():
            try: popup.hide(); popup.deleteLater()
            except: pass
        QTimer.singleShot(4000, _dismiss)

    def _start_clock(self):
        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000); self._tick()

    def _tick(self):
        n = QDateTime.currentDateTime()
        self._clock_lbl.setText(
            n.toString("dd MMM yyyy") + "   " + n.toString("hh:mm:ss AP")
        )

    # ================================================================
    # F-KEY GLOBAL HANDLER (overrides keyPressEvent)
    # ================================================================

    def keyPressEvent(self, event):
        fmap = {
            Qt.Key.Key_F1:0, Qt.Key.Key_F2:1, Qt.Key.Key_F3:2, Qt.Key.Key_F4:3,
            Qt.Key.Key_F5:4, Qt.Key.Key_F6:5, Qt.Key.Key_F7:6, Qt.Key.Key_F8:7,
        }
        idx = fmap.get(event.key())
        if idx is not None:
            self._add_quick_key(idx); return
        super().keyPressEvent(event)

    # ================================================================
    # SEARCH
    # ================================================================

    def _search_key_press(self, event):
        if event.key() == Qt.Key.Key_Up:
            self.qty_spinbox.setFocus(); self.qty_spinbox.selectAll(); return
        elif event.key() == Qt.Key.Key_Down:
            if self.results_list.isVisible() and self.results_list.count() > 0:
                self.results_list.setCurrentRow(0)
                self.results_list.setFocus(); return
        QLineEdit.keyPressEvent(self.search_input, event)

    def _results_key_press(self, event):
        if event.key() == Qt.Key.Key_Down:
            cur = self.results_list.currentRow()
            if cur < self.results_list.count()-1:
                self.results_list.setCurrentRow(cur+1)
        elif event.key() == Qt.Key.Key_Up:
            cur = self.results_list.currentRow()
            if cur > 0: self.results_list.setCurrentRow(cur-1)
            else: self.search_input.setFocus()
        elif event.key() == Qt.Key.Key_Return:
            item = self.results_list.currentItem()
            if item: self._add_from_results(item)
        else:
            QListWidget.keyPressEvent(self.results_list, event)

    def _clean_barcode(self, text: str) -> str:
        """Strip common scanner prefix/suffix chars and whitespace."""
        # Strip whitespace and common scanner garbage
        text = text.strip().strip('\r\n\x00\x02\x03')
        # Some scanners add a leading/trailing * or $ or Fn
        for ch in ('*', '$', '%', '+', '/', '.'):
            text = text.strip(ch)
        return text.strip()

    def _handle_search_enter(self):
        qty  = self.qty_spinbox.value()
        text = self._clean_barcode(self.search_input.text())
        if not text:
            self._handle_checkout(); return

        # Try exact barcode
        p = get_product_by_barcode(text)
        if p:
            self._add_to_cart(p, qty)
            self._clear_search(); return

        # Full-text search
        results = get_products(search=text, limit=20)
        if len(results) == 1:
            self._add_to_cart(results[0], qty)
            self._clear_search()
        elif len(results) == 0:
            self._flash_not_found()
            self.search_input.clear()
        else:
            self._show_results(results)

    def _flash_not_found(self):
        """Flash the search bar red briefly when product not found."""
        original = self.search_input.styleSheet()
        self.search_input.setStyleSheet(f"""
            QLineEdit{{background:#FCEBEB;color:{RED};
            border:2px solid {RED};border-radius:17px;
            font-size:12px;padding:0 12px;}}
        """)
        self.search_input.setPlaceholderText("Product not found — try again")
        from PyQt6.QtCore import QTimer
        def _restore():
            self.search_input.setStyleSheet(original)
            self.search_input.setPlaceholderText("↵  Barcode  |  Search  ↵  Checkout")
        QTimer.singleShot(1200, _restore)

    def _show_results(self, results):
        self.results_list.clear()
        q = self._clean_barcode(self.search_input.text())
        if not results:
            self._flash_not_found()
            item = QListWidgetItem("  No products found")
            item.setForeground(QColor(MUTED))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.results_list.addItem(item)
            self.match_lbl.setText(f'0 matches for "{q}"')
        else:
            for p in results:
                tag = "  [GCT]" if p["gct_applicable"] else "  [No GCT]"
                item = QListWidgetItem(f"  {p['name']}  —  ${p['selling_price']:.2f}{tag}")
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.results_list.addItem(item)
            n = len(results)
            self.match_lbl.setText(
                f'{n} match{"es" if n != 1 else ""} for "{q}"')
        self.match_lbl.setVisible(True)
        self.results_list.setVisible(True)

    def _add_from_results(self, item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if p:
            self._add_to_cart(p, self.qty_spinbox.value())
            self._clear_search()

    def _clear_search(self):
        self.search_input.clear()
        self.qty_spinbox.setValue(1)
        self.results_list.setVisible(False)
        self.match_lbl.setVisible(False)
        self.match_lbl.clear()
        self.search_input.setFocus()

    # ================================================================
    # CART
    # ================================================================

    def _add_quick_key(self, idx):
        if idx >= len(self._quick_keys): return
        qk = self._quick_keys[idx]
        if not qk.get("product_id"): return
        p = get_product_by_id(qk["product_id"])
        if p:
            self._add_to_cart(p, self.qty_spinbox.value())
            self.qty_spinbox.setValue(1)

    def _add_to_cart(self, product: dict, qty: int = 1):
        pid   = product["id"]
        price = product["selling_price"]
        gct   = round(price * self._gct_rate, 2) if product["gct_applicable"] else 0.0
        cost  = product.get("cost", 0.0)

        # Merge if already in cart
        for item in self.cart:
            if item["id"] == pid:
                item["qty"] += qty
                self._apply_discount(item)
                self._refresh_table(); self._update_totals(); return

        item = {
            "id":               pid,
            "name":             product["name"],
            "qty":              qty,
            "price":            price,
            "cost":             cost,
            "gct":              gct,
            "gct_applicable":   product["gct_applicable"],
            "disc_level_id":    product.get("discount_level1"),
            "disc_level2_id":   product.get("discount_level2"),
            "inline_disc1_qty": product.get("inline_disc1_qty"),
            "inline_disc1_pct": product.get("inline_disc1_pct"),
            "inline_disc2_qty": product.get("inline_disc2_qty"),
            "inline_disc2_pct": product.get("inline_disc2_pct"),
            "discount_applied": 0.0,
            "total":            round((price + gct) * qty, 2),
            "barcode":          product["barcode"],
        }
        self._apply_discount(item)
        self.cart.append(item)
        self._refresh_table()
        self._update_totals()

        # Low stock warning
        if self._low_stock_warning:
            stock = product.get("stock", 0)
            if stock <= self._low_stock_threshold:
                self._show_low_stock_banner(product["name"], stock)

    def _show_low_stock_banner(self, name: str, stock: int):
        """Brief warning banner when a product is low on stock."""
        from PyQt6.QtWidgets import QFrame, QLabel, QHBoxLayout
        from PyQt6.QtCore import QTimer
        banner = QFrame(self)
        banner.setObjectName("lowStockBanner")
        banner.setStyleSheet("""
            QFrame#lowStockBanner {
                background: #b45309;
                border-radius: 8px;
            }
        """)
        banner.setFixedSize(320, 48)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(14, 0, 14, 0)
        lbl = QLabel(f"⚠  Low stock: {name}  ({stock} remaining)")
        lbl.setStyleSheet("color:white;font-size:11px;font-weight:600;background:transparent;")
        bl.addWidget(lbl)
        banner.move(self.width() - banner.width() - 20, 56)
        banner.show(); banner.raise_()
        QTimer.singleShot(3500, banner.deleteLater)

    def _on_cart_double_click(self, row: int, col: int):
        """Allow qty editing on double-click if the feature is enabled."""
        if not self._allow_qty_edit:
            return
        if col != 1:   # column 1 is Qty
            return
        if row >= len(self.cart):
            return
        item = self.cart[row]
        from PyQt6.QtWidgets import QSpinBox
        editor = QSpinBox(self.cart_table)
        editor.setMinimum(1)
        editor.setMaximum(9999)
        editor.setValue(item["qty"])
        editor.setStyleSheet(f"""
            QSpinBox {{
                background: {AMBER_BG};
                border: 2px solid {AMBER};
                border-radius: 4px;
                color: {DARK_CARD};
                font-weight: 600;
                padding: 2px 4px;
            }}
        """)
        self.cart_table.setCellWidget(row, col, editor)
        editor.setFocus()
        editor.selectAll()

        def _commit():
            new_qty = editor.value()
            item["qty"] = new_qty
            self._apply_discount(item)
            self.cart_table.removeCellWidget(row, col)
            self._refresh_table()
            self._update_totals()

        editor.editingFinished.connect(_commit)

    def _apply_discount(self, item):
        """Apply level-1 / level-2 discount based on qty thresholds.

        Priority:
          1. Named discount levels (discount_level1/2 FK → discount_levels table)
          2. Inline discount fields (inline_disc1/2_qty/pct) set by DBF import —
             these are stored directly on the product and never appear in the
             edit form, keeping the global levels list clean.
        """
        qty      = item["qty"]
        price    = item["price"]
        gct_unit = item["gct"]
        rules    = self._disc_rules
        disc_pct = 0.0

        # Named discount levels (global, editable in settings)
        lvl1_id = item.get("disc_level_id") or item.get("discount_level1")
        lvl2_id = item.get("disc_level2_id") or item.get("discount_level2")
        lvl1 = rules.get(lvl1_id)
        lvl2 = rules.get(lvl2_id)

        if lvl2 and qty >= lvl2["min_qty"]:
            disc_pct = lvl2["pct"]
        elif lvl1 and qty >= lvl1["min_qty"]:
            disc_pct = lvl1["pct"]

        # Inline discount fallback (DBF-imported, not in global levels list)
        if disc_pct == 0.0:
            i2_qty = item.get("inline_disc2_qty")
            i2_pct = item.get("inline_disc2_pct")
            i1_qty = item.get("inline_disc1_qty")
            i1_pct = item.get("inline_disc1_pct")
            if i2_qty and i2_pct and qty >= i2_qty:
                disc_pct = i2_pct
            elif i1_qty and i1_pct and qty >= i1_qty:
                disc_pct = i1_pct

        disc_per_unit            = round(price * disc_pct / 100, 2)
        item["discount_applied"] = disc_per_unit
        item["total"]            = round((price - disc_per_unit + gct_unit) * qty, 2)

    def _handle_remove(self, row: int):
        """Remove a single cart item — respects require_remove_auth setting."""
        if not (0 <= row < len(self.cart)): return
        if get_bool("require_remove_auth", False):
            from ui.cashier.void_dialog import VoidDialog
            dlg = VoidDialog(self.cart, pre_select=[row], mode="remove", parent=self)
            if dlg.exec():
                for it in dlg.voided_items:
                    if it in self.cart: self.cart.remove(it)
                self._refresh_table(); self._update_totals()
        else:
            self.cart.pop(row)
            self._refresh_table(); self._update_totals()

    def _update_qty(self, row: int, new_qty: int):
        """Called when inline qty spinbox changes."""
        if not (0 <= row < len(self.cart)): return
        item = self.cart[row]
        item["qty"] = new_qty
        # Reapply discount for new qty
        self._apply_discount(item)
        # Refresh just totals and the current row total cell (avoid full rebuild loop)
        self._update_totals()
        # Update total cell directly
        from PyQt6.QtGui import QColor
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        disc   = item.get("discount_applied", 0.0)
        disc_t = round(disc * new_qty, 2)
        dc     = AMBER_DARK if disc > 0 else "#aaa"
        disc_item = QTableWidgetItem(f"-${disc_t:.2f}" if disc > 0 else "—")
        disc_item.setForeground(QColor(dc)); disc_item.setTextAlignment(C)
        self.cart_table.setItem(row, 3, disc_item)
        gct_item = QTableWidgetItem(f"${item['gct'] * new_qty:.2f}")
        gct_item.setForeground(QColor(AMBER_DARK)); gct_item.setTextAlignment(C)
        self.cart_table.setItem(row, 4, gct_item)
        total_item = QTableWidgetItem(f"${item['total']:.2f}")
        total_item.setForeground(QColor(AMBER_DARK)); total_item.setTextAlignment(C)
        self.cart_table.setItem(row, 5, total_item)

    def _remove_from_cart(self, row: int):
        if 0 <= row < len(self.cart):
            self.cart.pop(row)
            self._refresh_table(); self._update_totals()

    def _clear_cart(self):
        if not self.cart: return
        if get_bool("require_remove_auth", False):
            from ui.cashier.void_dialog import VoidDialog
            dlg = VoidDialog(self.cart, pre_select=list(range(len(self.cart))),
                             mode="void", parent=self)
            if dlg.exec():
                self.carts[self.active_cart] = []
                self._refresh_table(); self._update_totals()
        else:
            self.carts[self.active_cart] = []
            self._refresh_table(); self._update_totals()

    # ── Cart navigation ───────────────────────────────────────────────

    def _prev_cart(self):
        self.active_cart = (self.active_cart - 1) % 3; self._switch_cart()

    def _next_cart(self):
        self.active_cart = (self.active_cart + 1) % 3; self._switch_cart()

    def _update_cart_label(self):
        """Update cart label with item count on a second line."""
        idx         = self.active_cart + 1
        total_items = len(self.cart)
        self._cart_lbl.setText(f"Cart {idx}")
        self._cart_lbl.setStyleSheet(
            "color:white;font-size:16px;font-weight:700;background:transparent;"
        )
        if total_items:
            self._cart_items_lbl.setText(f"({total_items} item{'s' if total_items != 1 else ''})")
            self._cart_items_lbl.setVisible(True)
        else:
            self._cart_items_lbl.setVisible(False)

    def _switch_cart(self):
        color = CART_COLORS[self.active_cart]
        self._update_cart_label()
        for attr in ["_cart_section", "subtotal_label_frame",
                     "gct_label_frame", "discount_label_frame", "total_label_frame"]:
            w = getattr(self, attr, None)
            if w: w.setStyleSheet(f"background:{color};border:none;")
        self.results_list.setVisible(False)
        self.search_input.clear()
        self._refresh_table(); self._update_totals()

    # ── Table refresh ─────────────────────────────────────────────────

    def _refresh_table(self):
        if hasattr(self, '_update_cart_label'): self._update_cart_label()
        self.cart_table.setRowCount(len(self.cart))
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        L = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        for row, item in enumerate(self.cart):
            def cell(text, color=DARK_CARD, align=L):
                c = QTableWidgetItem(str(text))
                c.setForeground(QColor(color))
                c.setTextAlignment(align)
                return c

            disc   = item.get("discount_applied", 0.0)
            disc_t = round(disc * item["qty"], 2)
            dc     = AMBER_DARK if disc > 0 else "#aaa"

            self.cart_table.setItem(row, 0, cell(item["name"]))

            # Inline qty spinbox
            qty_spin = QSpinBox()
            qty_spin.setMinimum(1); qty_spin.setMaximum(9999)
            qty_spin.setValue(item["qty"])
            qty_spin.setStyleSheet(f"""
                QSpinBox{{background:transparent;color:{DARK_CARD};
                border:none;font-size:12px;font-weight:600;}}
                QSpinBox:focus{{background:white;border:1px solid {AMBER};border-radius:4px;}}
                QSpinBox::up-button,QSpinBox::down-button{{width:14px;}}
            """)
            qty_spin.valueChanged.connect(lambda val, r=row: self._update_qty(r, val))
            self.cart_table.setCellWidget(row, 1, qty_spin)

            self.cart_table.setItem(row, 2, cell(f"${item['price']:.2f}", AMBER_DARK, C))
            self.cart_table.setItem(row, 3, cell(
                f"-${disc_t:.2f}" if disc > 0 else "—", dc, C
            ))
            self.cart_table.setItem(row, 4, cell(
                f"${item['gct'] * item['qty']:.2f}", AMBER_DARK, C
            ))
            self.cart_table.setItem(row, 5, cell(f"${item['total']:.2f}", AMBER_DARK, C))

            rm = QPushButton("✕")
            rm.setStyleSheet(f"""
                QPushButton{{background:{RED};color:white;border:none;
                border-radius:4px;font-size:12px;font-weight:800;
                min-width:26px;min-height:26px;}}
                QPushButton:hover{{background:#7A1E1E;}}
            """)
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.clicked.connect(lambda _, r=row: self._handle_remove(r))
            self.cart_table.setCellWidget(row, 6, rm)
            self.cart_table.setRowHeight(row, 38)

    def _update_totals(self):
        # Update cart label (name + item count)
        self._update_cart_label()
        subtotal = sum(item["price"] * item["qty"] for item in self.cart)
        gct      = sum(item["gct"]   * item["qty"] for item in self.cart)
        discount = sum(item.get("discount_applied", 0.0) * item["qty"] for item in self.cart)
        total    = subtotal + gct - discount
        self.subtotal_label.setText(f"${subtotal:.2f}")
        self.gct_label.setText(f"${gct:.2f}")
        self.discount_label.setText(f"${discount:.2f}")
        self.total_label.setText(f"${total:.2f}")

    # ================================================================
    # CHECKOUT
    # ================================================================

    def _add_misc_item(self):
        """Open misc item dialog and add result to cart."""
        from ui.cashier.misc_dialog import MiscDialog
        dlg = MiscDialog(parent=self)
        if dlg.exec():
            item = dlg.result_item()
            if item:
                # Merge if same description already in cart
                for existing in self.cart:
                    if existing["name"] == item["name"] and existing["price"] == item["price"]:
                        existing["qty"] += item["qty"]
                        existing["total"] = round(
                            (existing["price"] + existing["gct"]) * existing["qty"], 2
                        )
                        self._refresh_table(); self._update_totals(); return
                self.cart.append(item)
                self._refresh_table(); self._update_totals()

    def _handle_void(self):
        """Remove Items button — respects require_remove_auth setting."""
        if not self.cart: return
        if get_bool("require_remove_auth", False):
            from ui.cashier.void_dialog import VoidDialog
            dlg = VoidDialog(self.cart, pre_select=list(range(len(self.cart))),
                             mode="void", parent=self)
            if dlg.exec():
                for it in dlg.voided_items:
                    if it in self.cart: self.cart.remove(it)
                self._refresh_table(); self._update_totals()
        else:
            self.carts[self.active_cart] = []
            self._refresh_table(); self._update_totals()

    def _handle_checkout(self):
        if not self.cart: return
        # Block if no active session
        if not self._session_id:
            QMessageBox.warning(self, "No Active Session",
                "You don't have an active session.\n"
                "Please ask your supervisor to open one.")
            return
        from ui.cashier.checkout_dialog import CheckoutDialog
        dlg = CheckoutDialog(self.cart, self.user, self._session_id, self)
        if dlg.exec():
            self._show_change(dlg.change_given)
            if hasattr(dlg, "last_txn_id") and dlg.last_txn_id:
                self._last_txn_id = dlg.last_txn_id
                self._reprint_btn.setVisible(True)
            self.carts[self.active_cart] = []
            self._refresh_table(); self._update_totals()
            self.search_input.setFocus()
            # Auto-logout if supervisor closed the session during this sale
            if self._session_closing:
                self.logout_requested.emit()
                self.force_close()

    def _on_session_closed_by_supervisor(self, session_id: int):
        """Called when the supervisor closes this cashier's session."""
        if session_id != self._session_id:
            return
        self._session_closing = True
        self._session_id      = None
        self._show_supervisor_closed_banner()

    def _on_session_opened_by_supervisor(self, user_id: int):
        """Called when the supervisor opens a session for this cashier."""
        if user_id != self.user["id"]:
            return
        # Only activate if we were waiting (session gate was blocking)
        if self._session_id is not None:
            return
        session = get_open_session(self.user["id"])
        if not session:
            return
        self._session_id      = session["id"]
        self._session_closing = False
        self._show_session_activated_banner()

    def _show_session_activated_banner(self):
        """Brief green banner shown when supervisor opens a session for this cashier."""
        from PyQt6.QtWidgets import QFrame, QLabel, QHBoxLayout
        from PyQt6.QtCore import QTimer
        banner = QFrame(self)
        banner.setObjectName("activatedBanner")
        banner.setStyleSheet(f"""
            QFrame#activatedBanner {{
                background: {GREEN};
                border-radius: 8px;
            }}
        """)
        banner.setFixedSize(340, 48)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(14, 0, 14, 0)
        lbl = QLabel(f"✓  Session #{self._session_id:04d} opened — you can now process sales")
        lbl.setStyleSheet("color:white;font-size:11px;font-weight:600;background:transparent;")
        bl.addWidget(lbl)
        banner.move(self.width() - banner.width() - 20, 56)
        banner.show(); banner.raise_()
        QTimer.singleShot(4000, banner.deleteLater)

    def _show_supervisor_closed_banner(self):
        """Persistent banner shown when supervisor closes the session."""
        from PyQt6.QtWidgets import QFrame, QLabel, QHBoxLayout
        banner = QFrame(self)
        banner.setObjectName("closedBanner")
        banner.setStyleSheet(f"""
            QFrame#closedBanner {{
                background: {RED};
                border: none;
                border-radius: 0px;
            }}
        """)
        banner.setFixedHeight(40)
        banner.setFixedWidth(self.width())
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel("⚠  Your session has been closed by your supervisor. "
                     "Complete your current sale to be logged out.")
        lbl.setStyleSheet("color:white;font-size:12px;font-weight:600;background:transparent;")
        bl.addWidget(lbl)
        banner.move(0, 48)   # just below topbar
        banner.show()
        banner.raise_()

    def _show_change(self, change: float):
        self._change_display.setText(f"${change:.2f}")
        self._change_frame.setVisible(True)

    def _reprint_last(self):
        if not self._last_txn_id: return
        from utils.print_manager import reprint_receipt
        reprint_receipt(self._last_txn_id, parent=self)

    # ================================================================
    # PRICE CHECK
    # ================================================================

    def _price_check(self):
        """Open the new standalone price check dialog."""
        from ui.cashier.price_check_dialog import PriceCheckDialog
        dlg = PriceCheckDialog(parent=self)
        dlg._gct_rate = self._gct_rate
        if dlg.exec():
            product = dlg.get_selected_product()
            if product:
                self._add_to_cart(product, qty=1)
                self.search_input.setFocus()

    # ================================================================
    # LOGOUT
    # ================================================================

    def _handle_logout(self):
        reply = QMessageBox.question(
            self, "Logout", "Are you sure you want to logout?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Session stays open — only closed manually by supervisor
            self.logout_requested.emit()
            self.force_close()

    # ================================================================
    # DB HELPERS
    # ================================================================

    def _load_quick_keys(self) -> list:
        return get_quick_keys()

    def _load_discount_rules(self) -> dict:
        """Return {level_id: {min_qty, pct}} for named levels,
        and store per-product inline rules separately."""
        try:
            import sqlite3
            from config import DB_PRODUCTS
            con = sqlite3.connect(DB_PRODUCTS)
            con.row_factory = sqlite3.Row
            # Named global discount levels
            rows = con.execute(
                "SELECT id, min_quantity, discount_percent FROM discount_levels"
            ).fetchall()
            rules = {r[0]: {"min_qty": r[1], "pct": r[2]} for r in rows}
            # Per-product inline discount rules
            inline = con.execute(
                "SELECT id, inline_disc1_qty, inline_disc1_pct, "
                "inline_disc2_qty, inline_disc2_pct FROM products "
                "WHERE inline_disc1_qty IS NOT NULL OR inline_disc2_qty IS NOT NULL"
            ).fetchall()
            self._inline_disc_rules = {}
            for r in inline:
                tiers = []
                if r["inline_disc1_qty"] and r["inline_disc1_pct"]:
                    tiers.append({"min_qty": r["inline_disc1_qty"],
                                  "pct": r["inline_disc1_pct"]})
                if r["inline_disc2_qty"] and r["inline_disc2_pct"]:
                    tiers.append({"min_qty": r["inline_disc2_qty"],
                                  "pct": r["inline_disc2_pct"]})
                if tiers:
                    self._inline_disc_rules[r["id"]] = tiers
            con.close()
            return rules
        except Exception:
            self._inline_disc_rules = {}
            return {}

    def _reload_discount_rules(self):
        """Refresh discount rules from DB (call after manager saves changes)."""
        self._disc_rules = self._load_discount_rules()

    # ================================================================
    # STYLE HELPERS
    # ================================================================

    def _fkey_style(self, active: bool) -> str:
        if not active:
            return f"""QPushButton{{background:{DARK_3};color:#484f58;
                border:1px solid {DARK_4};border-radius:8px;font-size:10px;}}"""
        return f"""
            QPushButton{{background:{DARK_3};color:white;
            border:1px solid {DARK_4};border-radius:8px;
            font-size:10px;text-align:center;}}
            QPushButton:hover{{background:{AMBER};border-color:{AMBER};color:white;}}
            QPushButton:pressed{{background:{AMBER_DARK};}}
        """

    def _nav_btn_style(self) -> str:
        return """QPushButton{
            background:rgba(0,0,0,0.25);color:white;
            border:2px solid rgba(255,255,255,0.5);border-radius:17px;
            font-size:16px;font-weight:800;min-width:34px;min-height:34px;}
            QPushButton:hover{background:rgba(0,0,0,0.5);border-color:white;}
        """

    def _pill_btn_style(self) -> str:
        return f"""
            QPushButton{{background:{DARK_4};color:#ccc;
            border:1px solid #3a3a3a;border-radius:15px;
            font-size:11px;font-weight:500;padding:0 14px;}}
            QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}
        """
