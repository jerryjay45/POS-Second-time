"""
Pickup printer tab (Manager window).

Settings for the second printer at the serving station: when on, every completed sale
also prints a pickup ticket there (big order number, items and quantities, no prices).
Settings belong to this PC. See utils/pickup_ticket.py.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
                             QSpinBox, QMessageBox, QScrollArea, QFrame)

from core.db_config import set_many
from ui.manager.receipt_tab import _btn, _hint, _INPUT
from ui.shared.checkbox import make_checkbox
from ui.shared.theme import DARK_CARD, WARM_WHITE, WHITE, BORDER, GREEN
from utils import pickup_ticket as PT
from utils.printer_capabilities import list_print_queues


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;border:none;")
    return l


class PickupTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setStyleSheet(f"background:{WARM_WHITE};")
        scroll.setWidget(body)

        card = QFrame()
        card.setMaximumWidth(560)
        card.setStyleSheet(f"QFrame{{background:{WHITE};border:1px solid {BORDER};border-radius:10px;}}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        title = QLabel("Pickup printer (second printer)")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:15px;font-weight:700;border:none;")
        lay.addWidget(title)
        lay.addWidget(_hint("Prints a ticket at the serving station after each sale: big order "
                            "number, items and quantities, no prices. The cashier receipt is "
                            "not changed. These settings are for this PC only."))

        self.enabled_cb = make_checkbox("Print a pickup ticket on every sale", False)
        lay.addWidget(self.enabled_cb)

        lay.addWidget(_lbl("Windows printer at the serving station"))
        row = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.printer_combo.setEditable(True)
        self.printer_combo.setStyleSheet(_INPUT)
        self.printer_combo.lineEdit().setPlaceholderText("Choose the second printer…")
        refresh = _btn("↻")
        refresh.setFixedWidth(36)
        refresh.setToolTip("Refresh printer list")
        refresh.clicked.connect(self._refresh_queues)
        row.addWidget(self.printer_combo, stretch=1)
        row.addWidget(refresh)
        lay.addLayout(row)
        lay.addWidget(_hint("Must be a different printer from the receipt printer. Leaving it "
                            "blank turns the feature off (it never falls back to the default printer)."))

        lay.addWidget(_lbl("Ticket title"))
        self.title_edit = QLineEdit()
        self.title_edit.setStyleSheet(_INPUT)
        self.title_edit.setMaxLength(30)
        self.title_edit.setPlaceholderText("e.g. PICKUP  (blank = none)")
        lay.addWidget(self.title_edit)

        self.time_cb = make_checkbox("Show the time of the sale", True)
        self.cashier_cb = make_checkbox("Show the cashier's name", False)
        self.bold_cb = make_checkbox("Print items in bold", True)
        for w in (self.time_cb, self.cashier_cb, self.bold_cb):
            lay.addWidget(w)

        lay.addWidget(_lbl("Copies per sale"))
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 3)
        self.copies_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.copies_spin)

        lay.addWidget(_lbl("Printer commands"))
        self.escpos_cb = make_checkbox("ESC/POS printer (big order number, bold items)", True)
        self.cutter_cb = make_checkbox("Printer has an automatic paper cutter", False)
        lay.addWidget(self.escpos_cb)
        lay.addWidget(self.cutter_cb)
        lay.addWidget(_hint("Untick ESC/POS for a printer that only prints plain text. Print mode "
                            "(raw / raster) follows the receipt printer's setting."))

        lay.addWidget(_lbl("Paper columns (blank = same as the receipt printer)"))
        self.cols_edit = QLineEdit()
        self.cols_edit.setStyleSheet(_INPUT)
        self.cols_edit.setMaximumWidth(120)
        self.cols_edit.setPlaceholderText("auto")
        lay.addWidget(self.cols_edit)

        lay.addWidget(_lbl("Blank lines fed after the ticket"))
        self.feed_spin = QSpinBox()
        self.feed_spin.setRange(0, 20)
        self.feed_spin.setStyleSheet(_INPUT)
        lay.addWidget(self.feed_spin)
        lay.addWidget(_hint("Enough to push the ticket past the tear bar. Not used when the printer "
                            "has an automatic cutter."))

        btns = QHBoxLayout()
        save = _btn("Save", primary=True)
        test = _btn("Print test ticket")
        save.clicked.connect(self._save)
        test.clicked.connect(self._test)
        btns.addWidget(save)
        btns.addWidget(test)
        btns.addStretch()
        lay.addLayout(btns)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{GREEN};font-size:11px;border:none;")
        lay.addWidget(self.status)

        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(24, 20, 24, 20)
        wrap.addWidget(card, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        wrap.addStretch()

        self._refresh_queues()
        self._load()

    # ── data ────────────────────────────────────────────────────────────
    def _refresh_queues(self, *_a):
        cur = self.printer_combo.currentText()
        self.printer_combo.clear()
        try:
            for q in list_print_queues():
                self.printer_combo.addItem(q["name"])
        except Exception:
            pass
        self.printer_combo.setEditText(cur)

    def _load(self):
        s = PT.load_settings()
        self.enabled_cb.setChecked(s["pickup_enabled"] == "1")
        self.printer_combo.setEditText(s["pickup_printer_name"])
        self.title_edit.setText(s["pickup_title"])
        self.time_cb.setChecked(s["pickup_show_time"] == "1")
        self.cashier_cb.setChecked(s["pickup_show_cashier"] == "1")
        self.bold_cb.setChecked(s["pickup_bold_items"] == "1")
        self.copies_spin.setValue(PT._int(s["pickup_copies"], 1, 3, 1))
        self.escpos_cb.setChecked(s["pickup_escpos"] == "1")
        self.cutter_cb.setChecked(s["pickup_has_cutter"] == "1")
        self.cols_edit.setText(s["pickup_columns"])
        self.feed_spin.setValue(PT._int(s["pickup_feed_lines"], 0, 20, 5))
        self._clean = self._values()          # baseline for the unsaved-changes check

    def is_dirty(self) -> bool:
        return self._values() != self._clean

    def reload_if_clean(self):
        """Refresher: pick up changes made on the Printer Setup page, unless there are edits here."""
        if not self.is_dirty():
            self._refresh_queues()
            self._load()

    def _values(self) -> dict[str, str]:
        return {
            "pickup_enabled":      "1" if self.enabled_cb.isChecked() else "0",
            "pickup_printer_name": self.printer_combo.currentText().strip(),
            "pickup_title":        self.title_edit.text().strip(),
            "pickup_show_time":    "1" if self.time_cb.isChecked() else "0",
            "pickup_show_cashier": "1" if self.cashier_cb.isChecked() else "0",
            "pickup_bold_items":   "1" if self.bold_cb.isChecked() else "0",
            "pickup_copies":       str(self.copies_spin.value()),
            "pickup_escpos":       "1" if self.escpos_cb.isChecked() else "0",
            "pickup_has_cutter":   "1" if self.cutter_cb.isChecked() else "0",
            "pickup_columns":      self.cols_edit.text().strip(),
            "pickup_feed_lines":   str(self.feed_spin.value()),
        }

    def _validate(self, v: dict[str, str]) -> str:
        if v["pickup_enabled"] == "1" and not v["pickup_printer_name"]:
            return "Choose the serving-station printer, or untick the feature."
        if v["pickup_columns"]:
            if not v["pickup_columns"].isdigit() or not 16 <= int(v["pickup_columns"]) <= 80:
                return "Paper columns must be a number from 16 to 80 (or blank)."
        try:
            from core.db_config import get as cfg_get
            rec = cfg_get("receipt_printer_name", "").strip()
            if v["pickup_printer_name"] and rec and v["pickup_printer_name"].lower() == rec.lower():
                return ("The pickup printer is the same as the receipt printer. Choose a "
                        "different one.")
        except Exception:
            pass
        return ""

    def _save(self) -> bool:
        v = self._values()
        err = self._validate(v)
        if err:
            QMessageBox.warning(self, "Pickup printer", err)
            return False
        set_many(v)
        self._clean = v
        self.status.setText("✓ Saved")
        return True

    def _test(self):
        v = self._values()
        if not v["pickup_printer_name"]:
            QMessageBox.warning(self, "Pickup printer", "Choose a printer first.")
            return
        err = self._validate(v)
        if err:
            QMessageBox.warning(self, "Pickup printer", err)
            return
        set_many(v)                      # the test prints with what is on screen
        self._clean = v
        try:
            from utils.print_manager import print_pickup
            print_pickup(PT.sample_receipt(), test=True)
            self.status.setText("✓ Test ticket sent to the pickup printer")
        except Exception as e:
            QMessageBox.warning(self, "Pickup printer", f"Could not print: {e}")
