"""
ui/shared/searchable_product_combo.py
A searchable popup picker for selecting a single (non-case) product.

Queries the DB on each keystroke (debounced 250ms) and returns at most
*limit* results — safe for databases with thousands of products.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QFrame, QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, BORDER,
    DARK, DARK_CARD, MUTED, WARM_WHITE, WHITE,
)
from utils.currency import format_currency


class SearchableProductCombo(QWidget):
    """
    Searchable popup picker that selects a single (non-case) product.

    Public API
    ----------
    selected_id()  -> int | None
    selected_name() -> str
    set_value(product_id)     — restore a saved selection
    clear_value()             — reset to None
    exclude_id(product_id)    — exclude a product from results (self-reference)

    Signals
    -------
    selectionChanged(product_id: int | None, product_name: str)
    """

    selectionChanged = pyqtSignal(object, str)

    _LIMIT = 50   # max results per search

    def __init__(self, parent=None, none_label: str = "— None (own price) —",
                 show_price: bool = False, price_field: str = "effective_cost",
                 exclude_cases: bool = True, exclude_variant_members: bool = True):
        super().__init__(parent)
        self._selected_id   = None
        self._selected_name = ""
        self._exclude_id    = None
        self._none_label    = none_label
        self._show_price    = show_price
        self._price_field   = price_field
        self._exclude_cases = exclude_cases
        self._exclude_variant_members = exclude_variant_members
        self._debounce      = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._run_search)
        self._build()

    # ── Public API ────────────────────────────────────────────────────

    def selected_id(self) -> int | None:
        return self._selected_id

    def selected_name(self) -> str:
        return self._selected_name

    def set_value(self, product_id: int | None):
        if product_id is None:
            self.clear_value()
            return
        from core.db_products import get_product_by_id
        p = get_product_by_id(product_id)
        if p:
            self._selected_id   = p["id"]
            self._selected_name = p["name"]
            label = p["name"]
            if self._show_price:
                label += f"  ({format_currency(p[self._price_field])})"
            self._trigger.setText(label)
            self._update_trigger_style(selected=True)
        else:
            self.clear_value()

    def clear_value(self):
        self._selected_id   = None
        self._selected_name = ""
        self._trigger.setText(self._none_label)
        self._update_trigger_style(selected=False)

    def exclude_id(self, product_id: int | None):
        """Exclude a product from results (used to prevent a product linking to itself)."""
        self._exclude_id = product_id

    # ── Build ─────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Trigger button
        self._trigger = QPushButton(self._none_label)
        self._trigger.setFixedHeight(34)
        self._trigger.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_trigger_style(selected=False)
        self._trigger.clicked.connect(self._toggle_popup)
        layout.addWidget(self._trigger)

        # Popup
        self._popup = QFrame(self, Qt.WindowType.Popup)
        self._popup.setWindowFlags(Qt.WindowType.Popup)
        self._popup.setStyleSheet(f"""
            QFrame {{
                background: {WHITE};
                border: 1.5px solid {AMBER};
                border-radius: 8px;
            }}
        """)
        pl = QVBoxLayout(self._popup)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(6)

        # Search input
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Type name or barcode…")
        self._search.setFixedHeight(30)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: {WARM_WHITE};
                border: 1px solid {BORDER};
                border-radius: 5px;
                padding: 0 8px;
                font-size: 12px;
                color: {DARK_CARD};
            }}
            QLineEdit:focus {{ border-color: {AMBER}; }}
        """)
        self._search.textChanged.connect(self._on_search_changed)
        pl.addWidget(self._search)

        # Hint label
        self._hint = QLabel("Type to search…")
        self._hint.setStyleSheet(f"color:{MUTED};font-size:10px;padding:0 2px;")
        pl.addWidget(self._hint)

        # Results list
        self._list = QListWidget()
        self._list.setFixedHeight(200)
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: {WHITE};
                border: none;
                font-size: 12px;
                color: {DARK_CARD};
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{ background: {AMBER_LIGHTEST}; }}
            QListWidget::item:selected {{ background: {AMBER}; color: {DARK}; }}
        """)
        self._list.itemClicked.connect(self._on_item_clicked)
        pl.addWidget(self._list)

        self._popup.setFixedWidth(320)
        self._populate_none_item()

    # ── Internals ─────────────────────────────────────────────────────

    def _toggle_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self._show_popup()

    def _show_popup(self):
        self._search.clear()
        self._list.clear()
        self._populate_none_item()
        self._hint.setText("Type to search…")
        pos = self.mapToGlobal(self._trigger.geometry().bottomLeft())
        self._popup.move(pos)
        self._popup.show()
        self._search.setFocus()

    def _on_search_changed(self, text: str):
        self._debounce.stop()
        if not text.strip():
            self._list.clear()
            self._populate_none_item()
            self._hint.setText("Type to search…")
        else:
            self._debounce.start()

    def _run_search(self):
        from core.db_products import get_products
        text = self._search.text().strip()
        if not text:
            return
        results = get_products(search=text, limit=self._LIMIT)
        # Case-linking (the original use of this widget) can't point at
        # another case or at a variant-group member (no stock of its own).
        # Other consumers — e.g. Quick Keys, which assigns a real sellable
        # product to an F-key — don't want this exclusion, so it's
        # configurable rather than hardcoded.
        results = [
            p for p in results
            if (not self._exclude_cases or not p["is_case"])
            and (not self._exclude_variant_members or not p["variant_group_id"])
            and p["id"] != self._exclude_id
        ]
        self._list.clear()
        self._populate_none_item()
        if not results:
            self._hint.setText("No products found.")
        else:
            shown = len(results)
            self._hint.setText(
                f"{shown} result{'s' if shown != 1 else ''}"
                + (f" (showing first {self._LIMIT})" if shown == self._LIMIT else "")
            )
            for p in results:
                # Alias-group members DO keep their own stock but share cost
                # with the group — show the effective_* field so it's never
                # stale (effective_cost for case-linking, effective_selling_
                # price for consumers like Quick Keys that show what the
                # customer pays, not the store's cost).
                price = p[self._price_field]
                item = QListWidgetItem(f"{p['name']}  ({format_currency(price)})")
                item.setData(Qt.ItemDataRole.UserRole, p["id"])
                item.setData(Qt.ItemDataRole.UserRole + 1, p["name"])
                item.setData(Qt.ItemDataRole.UserRole + 2, price)
                if p["id"] == self._selected_id:
                    item.setSelected(True)
                self._list.addItem(item)

    def _populate_none_item(self):
        none_item = QListWidgetItem(self._none_label)
        none_item.setData(Qt.ItemDataRole.UserRole, None)
        none_item.setForeground(QColor(MUTED))
        self._list.addItem(none_item)

    def _on_item_clicked(self, item: QListWidgetItem):
        pid   = item.data(Qt.ItemDataRole.UserRole)
        name  = item.data(Qt.ItemDataRole.UserRole + 1) or ""
        price = item.data(Qt.ItemDataRole.UserRole + 2)
        if pid is None:
            self.clear_value()
        else:
            self._selected_id   = pid
            self._selected_name = name
            label = f"{name}  ({format_currency(price)})" if self._show_price else name
            self._trigger.setText(label)
            self._update_trigger_style(selected=True)
        self._popup.hide()
        self.selectionChanged.emit(self._selected_id, self._selected_name)

    def _update_trigger_style(self, selected: bool):
        border = AMBER if selected else BORDER
        color  = DARK_CARD if selected else MUTED
        self._trigger.setStyleSheet(f"""
            QPushButton {{
                background: {WHITE};
                border: 1.5px solid {border};
                border-radius: 6px;
                color: {color};
                font-size: 12px;
                padding: 0 10px;
                text-align: left;
            }}
            QPushButton:hover {{ border-color: {AMBER}; }}
        """)
