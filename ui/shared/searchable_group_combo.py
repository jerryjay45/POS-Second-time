"""
ui/shared/searchable_group_combo.py
A searchable dropdown for price groups with inline creation.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QFrame,
    QLabel, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, BORDER, DARK_CARD,
    GREEN, LABEL_TEXT, MUTED, RED, WARM_WHITE, WHITE
)
from core.db_products import get_price_groups, add_price_group


class SearchableGroupCombo(QWidget):
    """
    Searchable dropdown for alias/variant price groups.

    Signals
    -------
    selectionChanged(group_id: int | None, group_name: str)
    """
    selectionChanged = pyqtSignal(object, str)   # (id or None, name)

    def __init__(self, type_: str, parent=None):
        """
        type_ : 'alias' or 'variant'
        """
        super().__init__(parent)
        self._type        = type_
        self._selected_id = None
        self._selected_nm = ""
        self._popup_open  = False
        self._build()

    # ── Build ─────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Trigger button (looks like a combobox) ────────────────────
        self._trigger = QPushButton("— None —")
        self._trigger.setFixedHeight(34)
        self._trigger.setCursor(Qt.CursorShape.PointingHandCursor)
        self._trigger.setStyleSheet(f"""
            QPushButton {{
                background: {WHITE};
                border: 1.5px solid {BORDER};
                border-radius: 6px;
                color: {MUTED};
                font-size: 12px;
                padding: 0 10px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {AMBER};
            }}
        """)
        self._trigger.clicked.connect(self._toggle_popup)
        layout.addWidget(self._trigger)

        # ── Popup ─────────────────────────────────────────────────────
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
        self._search.setPlaceholderText("🔍  Search or type new name…")
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
            QLineEdit:focus {{
                border-color: {AMBER};
            }}
        """)
        self._search.textChanged.connect(self._filter_list)
        # Force uppercase
        self._search.textChanged.connect(
            lambda t: self._search.setText(t.upper()) if t != t.upper() else None
        )
        pl.addWidget(self._search)

        # List
        self._list = QListWidget()
        self._list.setFixedHeight(160)
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
            QListWidget::item:hover {{
                background: {AMBER_LIGHTEST};
            }}
            QListWidget::item:selected {{
                background: {AMBER};
                color: white;
            }}
        """)
        self._list.itemClicked.connect(self._on_item_clicked)
        pl.addWidget(self._list)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
        pl.addWidget(div)

        # "+ New Group" button
        self._new_btn = QPushButton(f"＋  New {self._type.capitalize()} Group")
        self._new_btn.setFixedHeight(30)
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {AMBER};
                font-size: 12px;
                font-weight: 600;
                text-align: left;
                padding: 0 4px;
            }}
            QPushButton:hover {{
                color: {AMBER_DARK};
            }}
        """)
        self._new_btn.clicked.connect(self._create_new_group)
        pl.addWidget(self._new_btn)

        self._popup.setFixedWidth(300)
        self._refresh_list()

    # ── Public API ────────────────────────────────────────────────────

    def selected_id(self) -> int | None:
        return self._selected_id

    def set_value(self, group_id: int | None):
        """Set the current selection by group_id."""
        if group_id is None:
            self._selected_id = None
            self._selected_nm = ""
            self._trigger.setText("— None —")
            self._trigger.setStyleSheet(self._trigger.styleSheet().replace(
                f"color: {DARK_CARD}", f"color: {MUTED}"
            ))
            return
        for pg in get_price_groups(type_=self._type):
            if pg["id"] == group_id:
                self._selected_id = group_id
                self._selected_nm = pg["name"]
                self._trigger.setText(pg["name"])
                self._update_trigger_style(selected=True)
                return

    def clear_value(self):
        self.set_value(None)

    # ── Internals ─────────────────────────────────────────────────────

    def _toggle_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self._show_popup()

    def _show_popup(self):
        self._search.clear()
        self._refresh_list()
        # Position below trigger
        pos = self.mapToGlobal(self._trigger.geometry().bottomLeft())
        self._popup.move(pos)
        self._popup.show()
        self._search.setFocus()

    def _refresh_list(self, filter_text: str = ""):
        self._list.clear()
        # None option
        none_item = QListWidgetItem("— None —")
        none_item.setData(Qt.ItemDataRole.UserRole, None)
        none_item.setForeground(QColor(MUTED))
        self._list.addItem(none_item)
        for pg in get_price_groups(type_=self._type):
            if filter_text and filter_text not in pg["name"]:
                continue
            item = QListWidgetItem(pg["name"])
            item.setData(Qt.ItemDataRole.UserRole, pg["id"])
            if pg["id"] == self._selected_id:
                item.setSelected(True)
            self._list.addItem(item)

    def _filter_list(self, text: str):
        self._refresh_list(filter_text=text.upper())
        # Update new group button label
        if text.strip():
            self._new_btn.setText(f"＋  Create \"{text.upper()}\"")
        else:
            self._new_btn.setText(f"＋  New {self._type.capitalize()} Group")

    def _on_item_clicked(self, item: QListWidgetItem):
        gid  = item.data(Qt.ItemDataRole.UserRole)
        name = item.text() if gid is not None else ""
        self._selected_id = gid
        self._selected_nm = name
        self._trigger.setText(item.text())
        self._update_trigger_style(selected=gid is not None)
        self._popup.hide()
        self.selectionChanged.emit(gid, name)

    def _create_new_group(self):
        name = self._search.text().strip()
        if not name:
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(
                self, f"New {self._type.capitalize()} Group",
                "Group name:"
            )
            if not ok or not name.strip():
                return
            name = name.strip().upper()
        # Check for duplicate
        existing = [pg["name"] for pg in get_price_groups(type_=self._type)]
        if name in existing:
            QMessageBox.warning(self, "Duplicate",
                f"A {self._type} group named \"{name}\" already exists.")
            return
        gid = add_price_group(name, self._type)
        self._selected_id = gid
        self._selected_nm = name
        self._trigger.setText(name)
        self._update_trigger_style(selected=True)
        self._popup.hide()
        self.selectionChanged.emit(gid, name)

    def _update_trigger_style(self, selected: bool):
        color = DARK_CARD if selected else MUTED
        self._trigger.setStyleSheet(f"""
            QPushButton {{
                background: {WHITE};
                border: 1.5px solid {"#" + AMBER.lstrip("#") if selected else BORDER};
                border-radius: 6px;
                color: {color};
                font-size: 12px;
                padding: 0 10px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {AMBER};
            }}
        """)
