"""
ui/cashier/price_check_dialog.py
Standalone price check dialog — search products by barcode or name.

Features:
  - Live search results (dropdown list)
  - Barcode + name search
  - Shows price, GCT info, cost margin (if available)
  - Quick add to cart from results
  - Keyboard navigation
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QListWidget, QListWidgetItem, QSpacerItem, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QColor

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHT, AMBER_LIGHTEST,
    DARK, DARK_2, DARK_3, DARK_4, DARK_CARD,
    WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN,
)
from core.db_products import get_product_by_barcode, get_products


class PriceCheckDialog(QDialog):
    """Standalone price check dialog with live search."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Price Check")
        self.setFixedWidth(420)
        self.setStyleSheet(f"background:{WHITE};")
        self.selected_product = None
        self._gct_rate = 0.165  # Will be overridden by parent if needed
        self._search_timer = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel("▦  Price Check")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:16px;font-weight:700;letter-spacing:-0.3px;")
        lay.addWidget(title)

        # ── Hint ──────────────────────────────────────────────────────
        hint = QLabel("Scan barcode or enter product name")
        hint.setStyleSheet(f"color:{MUTED};font-size:11px;")
        lay.addWidget(hint)

        # ── Search input ───────────────────────────────────────────────
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍  Barcode or name…")
        self.search_input.setFixedHeight(40)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {WARM_WHITE};
                color: {DARK_CARD};
                border: 2px solid {BORDER};
                border-radius: 10px;
                padding: 0 14px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {AMBER};
                background: {WHITE};
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.keyPressEvent = self._search_key_press
        lay.addWidget(self.search_input)

        # ── Results list (live search dropdown) ────────────────────────
        self.results_list = QListWidget()
        self.results_list.setVisible(False)
        self.results_list.setMaximumHeight(200)
        self.results_list.setStyleSheet(f"""
            QListWidget {{
                background: {WHITE};
                color: {DARK_CARD};
                border: 2px solid {AMBER};
                border-top: none;
                border-radius: 0 0 10px 10px;
                font-size: 12px;
                margin-top: -2px;
            }}
            QListWidget::item {{
                padding: 10px 14px;
                border-bottom: 1px solid {BORDER_LIGHT};
            }}
            QListWidget::item:selected {{
                background: {AMBER};
                color: white;
            }}
            QListWidget::item:hover {{
                background: {AMBER_LIGHTEST};
            }}
        """)
        self.results_list.itemClicked.connect(self._on_result_selected)
        self.results_list.keyPressEvent = self._results_key_press
        lay.addWidget(self.results_list)

        # ── Result detail frame (hidden by default) ────────────────────
        self.result_frame = QFrame()
        self.result_frame.setVisible(False)
        self.result_frame.setStyleSheet(
            f"background:{WARM_WHITE};border:1.5px solid {BORDER};border-radius:10px;"
        )
        rf_lay = QVBoxLayout(self.result_frame)
        rf_lay.setContentsMargins(16, 14, 16, 14)
        rf_lay.setSpacing(6)

        # Product name
        self.result_name = QLabel("")
        self.result_name.setStyleSheet(f"color:{DARK_CARD};font-size:14px;font-weight:700;")
        self.result_name.setWordWrap(True)
        rf_lay.addWidget(self.result_name)

        # Price (main)
        price_row = QHBoxLayout()
        price_label = QLabel("Price:")
        price_label.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;")
        self.result_price = QLabel("")
        self.result_price.setStyleSheet(f"color:{AMBER};font-size:20px;font-weight:800;")
        price_row.addWidget(price_label)
        price_row.addWidget(self.result_price)
        price_row.addStretch()
        rf_lay.addLayout(price_row)

        # GCT info
        self.result_gct = QLabel("")
        self.result_gct.setStyleSheet(f"color:{MUTED};font-size:11px;")
        rf_lay.addWidget(self.result_gct)

        # Stock info
        self.result_stock = QLabel("")
        self.result_stock.setStyleSheet(f"color:{MUTED};font-size:11px;")
        rf_lay.addWidget(self.result_stock)

        # Cost/margin info (if available)
        self.result_margin = QLabel("")
        self.result_margin.setStyleSheet(f"color:{MUTED};font-size:10px;font-style:italic;")
        rf_lay.addWidget(self.result_margin)

        # Not found message
        self.result_not_found = QLabel("Product not found")
        self.result_not_found.setStyleSheet(f"color:{RED};font-size:12px;font-weight:600;")
        self.result_not_found.setVisible(False)
        rf_lay.addWidget(self.result_not_found)

        lay.addWidget(self.result_frame)

        # ── Divider ────────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
        lay.addWidget(divider)

        # ── Button row ─────────────────────────────────────────────────
        btn_lay = QHBoxLayout()
        btn_lay.setSpacing(10)

        self.add_btn = QPushButton("➕  Add to Cart")
        self.add_btn.setFixedHeight(36)
        self.add_btn.setVisible(False)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background: {AMBER};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {AMBER_DARK}; }}
            QPushButton:pressed {{ background: #633806; }}
        """)
        self.add_btn.clicked.connect(self._add_to_cart)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(36)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {DARK_CARD};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: #555; }}
        """)
        close_btn.clicked.connect(self.reject)

        btn_lay.addWidget(self.add_btn)
        btn_lay.addStretch()
        btn_lay.addWidget(close_btn)
        lay.addLayout(btn_lay)

        # Focus on search input
        self.search_input.setFocus()

    # ── Search handlers ────────────────────────────────────────────────

    def _on_search_text_changed(self, text: str):
        """Live search with debounce."""
        if self._search_timer:
            self._search_timer.stop()
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self._do_search(text))
        self._search_timer.start(300)  # 300ms debounce

    def _do_search(self, text: str):
        """Execute the search."""
        text = text.strip()
        if not text:
            self.results_list.setVisible(False)
            self.result_frame.setVisible(False)
            self.selected_product = None
            self.add_btn.setVisible(False)
            return

        # Try exact barcode match first
        product = get_product_by_barcode(text)
        if product:
            self._show_single_result(product)
            return

        # Fall back to name search
        results = get_products(search=text, limit=15)
        if len(results) == 1:
            self._show_single_result(results[0])
        elif len(results) > 1:
            self._show_results_list(results)
        else:
            self._show_not_found()

    def _show_single_result(self, product: dict):
        """Display a single product result."""
        self.selected_product = product
        self.results_list.setVisible(False)
        self.result_frame.setVisible(True)

        # Populate result frame
        self.result_name.setText(product["name"])

        price = product["selling_price"]
        self.result_price.setText(f"${price:.2f}")

        # GCT info
        if product.get("gct_applicable"):
            gct_amt = price * self._gct_rate
            self.result_gct.setText(f"GCT ({self._gct_rate*100:.1f}%): ${gct_amt:.2f}  ·  Total incl. tax: ${price + gct_amt:.2f}")
        else:
            self.result_gct.setText("No GCT applicable")

        # Stock info
        stock = product.get("stock", 0)
        self.result_stock.setText(f"Stock: {stock} unit{'s' if stock != 1 else ''}")

        # Cost/margin if available
        cost = product.get("cost", 0)
        if cost > 0:
            margin = price - cost
            margin_pct = (margin / cost * 100) if cost > 0 else 0
            self.result_margin.setText(f"Cost: ${cost:.2f}  ·  Margin: ${margin:.2f} ({margin_pct:.1f}%)")
        else:
            self.result_margin.setText("")

        self.result_not_found.setVisible(False)
        self.result_name.setVisible(True)
        self.result_price.setVisible(True)
        self.result_gct.setVisible(True)
        self.result_stock.setVisible(True)
        self.add_btn.setVisible(True)

    def _show_results_list(self, results: list):
        """Display search results in dropdown list."""
        self.results_list.clear()
        self.result_frame.setVisible(False)
        self.add_btn.setVisible(False)

        for p in results:
            tag = "  [GCT]" if p.get("gct_applicable") else "  [No GCT]"
            item_text = f"{p['name']}  —  ${p['selling_price']:.2f}{tag}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.results_list.addItem(item)

        self.results_list.setVisible(True)
        self.results_list.setCurrentRow(0)

    def _show_not_found(self):
        """Show 'not found' message."""
        self.results_list.setVisible(False)
        self.result_frame.setVisible(True)
        self.result_name.setVisible(False)
        self.result_price.setVisible(False)
        self.result_gct.setVisible(False)
        self.result_stock.setVisible(False)
        self.result_margin.setVisible(False)
        self.result_not_found.setVisible(True)
        self.selected_product = None
        self.add_btn.setVisible(False)

    def _on_result_selected(self, item: QListWidgetItem):
        """Result list item clicked."""
        product = item.data(Qt.ItemDataRole.UserRole)
        if product:
            self._show_single_result(product)

    # ── Keyboard navigation ────────────────────────────────────────────

    def _search_key_press(self, event):
        """Handle special keys in search input."""
        if event.key() == Qt.Key.Key_Down:
            if self.results_list.isVisible() and self.results_list.count() > 0:
                self.results_list.setCurrentRow(0)
                self.results_list.setFocus()
        else:
            QLineEdit.keyPressEvent(self.search_input, event)

    def _results_key_press(self, event):
        """Handle special keys in results list."""
        if event.key() == Qt.Key.Key_Down:
            cur = self.results_list.currentRow()
            if cur < self.results_list.count() - 1:
                self.results_list.setCurrentRow(cur + 1)
        elif event.key() == Qt.Key.Key_Up:
            cur = self.results_list.currentRow()
            if cur > 0:
                self.results_list.setCurrentRow(cur - 1)
            else:
                self.search_input.setFocus()
        elif event.key() == Qt.Key.Key_Return:
            item = self.results_list.currentItem()
            if item:
                self._on_result_selected(item)
        else:
            QListWidget.keyPressEvent(self.results_list, event)

    # ── Add to cart ────────────────────────────────────────────────────

    def _add_to_cart(self):
        """Add selected product to cart and close."""
        if self.selected_product:
            self.accept()

    def get_selected_product(self) -> dict:
        """Return the selected product after dialog closes."""
        return self.selected_product
