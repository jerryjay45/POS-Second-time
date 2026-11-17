"""
Printer Setup — the simple printer page, for supervisors and managers.

Everyday settings only, all for THIS PC:
  Receipt printer : Windows printer, paper width, copies, cash drawer, test receipt
  Pickup printer  : on/off, Windows printer, copies, test ticket

Print mode, fonts, cutter, columns, margins, calibration and the receipt look stay in
the manager-only Receipt (advanced) and Pickup (advanced) pages.  Both pages write the
same settings, so each one reloads when shown again unless it has unsaved edits.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
                             QMessageBox, QScrollArea, QFrame, QSizePolicy)

from core.db_config import get as cfg_get, set_many
from ui.manager.receipt_tab import _btn, _hint as _plain_hint, _INPUT
from ui.shared.checkbox import make_checkbox
from ui.shared.theme import DARK_CARD, WARM_WHITE, WHITE, BORDER, GREEN, RED, MUTED
from utils import pickup_ticket as PT
from utils import receipt_layout as RL
from utils import receipt_setup_io as IO
from utils.printer_capabilities import (STANDARD_WIDTHS_MM, PLAUSIBLE_RECEIPT_MM, check_queue,
                                        detect_reported_width_mm, list_print_queues)

_WARN = "#B45309"


def _hint(text: str) -> QLabel:
    """Wrapped hint that is never squeezed: it asks for the height its text needs."""
    l = _plain_hint(text)
    l.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
    return l


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;border:none;")
    return l


def _card(title: str, note: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setMinimumWidth(520)
    card.setMaximumWidth(560)
    card.setStyleSheet(f"QFrame{{background:{WHITE};border:1px solid {BORDER};border-radius:10px;}}")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(8)
    t = QLabel(title)
    t.setStyleSheet(f"color:{DARK_CARD};font-size:15px;font-weight:700;border:none;")
    lay.addWidget(t)
    lay.addWidget(_hint(note))
    return card, lay


class PrinterSetupTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = True
        self._queues: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setStyleSheet(f"background:{WARM_WHITE};")
        scroll.setWidget(body)
        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(24, 20, 24, 20)
        wrap.setSpacing(14)

        # ── receipt printer ─────────────────────────────────────────
        body.setMinimumHeight(0)
        card, lay = _card("Receipt printer (cashier)",
                          "For this PC only. Print mode, fonts, paper cutter and calibration are "
                          "set by a manager under Receipt (advanced).")
        lay.addWidget(_lbl("Windows printer"))
        row = QHBoxLayout()
        self.r_printer = QComboBox()
        self.r_printer.setEditable(True)
        self.r_printer.setStyleSheet(_INPUT)
        self.r_printer.lineEdit().setPlaceholderText("Leave blank to use the Windows default printer…")
        refresh = _btn("↻")
        refresh.setFixedWidth(36)
        refresh.setToolTip("Refresh printer list")
        refresh.clicked.connect(self._refresh_queues)
        row.addWidget(self.r_printer, stretch=1)
        row.addWidget(refresh)
        lay.addLayout(row)
        self.check_lbl = QLabel("")
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.check_lbl.setStyleSheet("border:none;font-size:11px;")
        self.check_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        lay.addWidget(self.check_lbl)

        lay.addWidget(_lbl("Paper width"))
        row = QHBoxLayout()
        self.r_width = QComboBox()
        for mm in STANDARD_WIDTHS_MM:
            self.r_width.addItem(f"{mm} mm", mm)
        self.r_width.setStyleSheet(_INPUT)
        detect = _btn("Detect")
        detect.clicked.connect(self._detect_width)
        row.addWidget(self.r_width, stretch=1)
        row.addWidget(detect)
        lay.addLayout(row)
        self.width_note = _hint("")
        lay.addWidget(self.width_note)

        lay.addWidget(_lbl("Copies per sale"))
        self.r_copies = QSpinBox()
        self.r_copies.setRange(1, 5)
        self.r_copies.setStyleSheet(_INPUT)
        lay.addWidget(self.r_copies)

        self.r_drawer = make_checkbox("Open the cash drawer on cash / split-tender sales", False)
        lay.addWidget(self.r_drawer)
        lay.addWidget(_hint("The drawer must be plugged into the receipt printer."))
        test_r = _btn("Print test receipt")
        test_r.clicked.connect(self._test_receipt)
        lay.addWidget(test_r, alignment=Qt.AlignmentFlag.AlignLeft)
        wrap.addWidget(card)

        # ── pickup printer ──────────────────────────────────────────
        card, lay = _card("Pickup printer (serving station)",
                          "Prints a ticket with a big order number and the items (no prices) after "
                          "each sale. Title, cutter, columns and feed are set by a manager under "
                          "Pickup (advanced).")
        self.p_enabled = make_checkbox("Print a pickup ticket on every sale", False)
        lay.addWidget(self.p_enabled)
        lay.addWidget(_lbl("Windows printer at the serving station"))
        row = QHBoxLayout()
        self.p_printer = QComboBox()
        self.p_printer.setEditable(True)
        self.p_printer.setStyleSheet(_INPUT)
        self.p_printer.lineEdit().setPlaceholderText("Choose the second printer…")
        refresh2 = _btn("↻")
        refresh2.setFixedWidth(36)
        refresh2.setToolTip("Refresh printer list")
        refresh2.clicked.connect(self._refresh_queues)
        row.addWidget(self.p_printer, stretch=1)
        row.addWidget(refresh2)
        lay.addLayout(row)
        lay.addWidget(_hint("Must be a different printer from the receipt printer. Blank turns it off "
                            "(it never falls back to the default printer)."))
        lay.addWidget(_lbl("Copies per sale"))
        self.p_copies = QSpinBox()
        self.p_copies.setRange(1, 3)
        self.p_copies.setStyleSheet(_INPUT)
        lay.addWidget(self.p_copies)
        test_p = _btn("Print test ticket")
        test_p.clicked.connect(self._test_pickup)
        lay.addWidget(test_p, alignment=Qt.AlignmentFlag.AlignLeft)
        wrap.addWidget(card)

        # ── save ────────────────────────────────────────────────────
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        wrap.addWidget(self.status)
        save = _btn("Save printer setup", primary=True)
        save.setFixedWidth(220)
        save.clicked.connect(self._save)
        wrap.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
        wrap.addStretch()

        self.r_printer.currentTextChanged.connect(self._update_check)
        self.r_width.currentIndexChanged.connect(self._update_width_note)
        self._refresh_queues()
        self._load()

    # ── loading / dirty tracking ────────────────────────────────────────
    def _refresh_queues(self, *_a):
        was = self._loading
        self._loading = True
        try:
            cur_r, cur_p = self.r_printer.currentText(), self.p_printer.currentText()
            self._queues = []
            try:
                self._queues = list_print_queues()
            except Exception:
                pass
            for combo, cur in ((self.r_printer, cur_r), (self.p_printer, cur_p)):
                combo.clear()
                for q in self._queues:
                    combo.addItem(q["name"])
                combo.setEditText(cur)
        finally:
            self._loading = was
        self._update_check()

    def _load(self):
        self._loading = True
        try:
            self.r_printer.setEditText(cfg_get("receipt_printer_name", ""))
            try:
                mm = int(float(cfg_get("receipt_paper_width_mm", "76") or 76))
            except ValueError:
                mm = 76
            closest = min(STANDARD_WIDTHS_MM, key=lambda s: abs(s - mm))
            self.r_width.setCurrentIndex(max(0, self.r_width.findData(closest)))
            self.r_copies.setValue(PT._int(cfg_get("receipt_copies", "1"), 1, 5, 1))
            self.r_drawer.setChecked(cfg_get("cash_drawer_kick_on_cash_sale", "0").strip() == "1")
            s = PT.load_settings()
            self.p_enabled.setChecked(s["pickup_enabled"] == "1")
            self.p_printer.setEditText(s["pickup_printer_name"])
            self.p_copies.setValue(PT._int(s["pickup_copies"], 1, 3, 1))
        finally:
            self._loading = False
        self._clean_r, self._clean_p = self._receipt_state(), self._pickup_state()
        self._update_check()
        self._update_width_note()

    def _receipt_state(self):
        return (self.r_printer.currentText().strip(), self.r_width.currentData(),
                self.r_copies.value(), self.r_drawer.isChecked())

    def _pickup_state(self):
        return (self.p_enabled.isChecked(), self.p_printer.currentText().strip(), self.p_copies.value())

    def is_dirty(self) -> bool:
        return self._receipt_state() != self._clean_r or self._pickup_state() != self._clean_p

    def reload_if_clean(self):
        """Refresher: pick up changes made on the advanced pages, unless there are edits here."""
        if not self.is_dirty():
            self._refresh_queues()
            self._load()

    # ── hints ───────────────────────────────────────────────────────────
    def _update_check(self, *_a):
        if self._loading or not hasattr(self, "check_lbl"):
            return
        colors = {"ok": GREEN, "info": MUTED, "warn": _WARN}
        icon = {"ok": "✓", "info": "•", "warn": "⚠"}
        try:
            notes = check_queue(self.r_printer.currentText(), cfg_get("receipt_printer_mode", "raw") or "raw",
                                self._queues or None)
        except Exception:
            notes = []
        self.check_lbl.setText("<br>".join(
            f"<span style='color:{colors[s]};'>{icon[s]} {t}</span>" for s, t in notes))

    def _update_width_note(self, *_a):
        if self._loading:
            return
        try:
            vals = {**IO.current_values(), "receipt_paper_width_mm": str(self.r_width.currentData())}
            cols = RL.layout_from_values(vals).columns
            manual = bool((cfg_get("receipt_columns", "") or "").strip())
        except Exception:
            return
        text = f"Prints about {cols} characters per line."
        if manual:
            text += (" The line length was set by printer calibration, so changing the width here "
                     "will not change it; a manager can re-run the calibration.")
        self.width_note.setText(text)

    def _detect_width(self):
        mm = detect_reported_width_mm(self.r_printer.currentText().strip())
        lo, hi = PLAUSIBLE_RECEIPT_MM
        if mm is None:
            msg = "Couldn't read a paper width from the driver — choose it manually."
        elif not (lo <= mm <= hi):
            msg = (f"The driver reports {mm} mm, which isn't a receipt width. "
                   "Choose the width manually.")
        else:
            closest = min(STANDARD_WIDTHS_MM, key=lambda s: abs(s - mm))
            self.r_width.setCurrentIndex(self.r_width.findData(closest))
            msg = f"Driver reports {mm} mm — set to {closest} mm."
        self.width_note.setText(msg)

    # ── validate / save / test ──────────────────────────────────────────
    def _receipt_values(self) -> dict[str, str]:
        return {"receipt_printer_name": self.r_printer.currentText().strip(),
                "receipt_paper_width_mm": str(self.r_width.currentData()),
                "receipt_copies": str(self.r_copies.value()),
                "cash_drawer_kick_on_cash_sale": "1" if self.r_drawer.isChecked() else "0"}

    def _pickup_values(self) -> dict[str, str]:
        return {"pickup_enabled": "1" if self.p_enabled.isChecked() else "0",
                "pickup_printer_name": self.p_printer.currentText().strip(),
                "pickup_copies": str(self.p_copies.value())}

    def _validate_receipt(self, v: dict[str, str]) -> str:
        for k in ("receipt_printer_name", "receipt_paper_width_mm", "receipt_copies"):
            ok, _n, err = RL.validate_value(k, v[k])
            if not ok:
                return f"{k.replace('receipt_', '').replace('_', ' ').capitalize()}: {err}"
        return ""

    def _validate_pickup(self, v: dict[str, str]) -> str:
        if v["pickup_enabled"] == "1" and not v["pickup_printer_name"]:
            return "Choose the serving-station printer, or untick the pickup ticket."
        rec = self.r_printer.currentText().strip()
        if v["pickup_printer_name"] and rec and v["pickup_printer_name"].lower() == rec.lower():
            return "The pickup printer is the same as the receipt printer. Choose a different one."
        return ""

    def _say(self, text: str, ok: bool = True):
        self.status.setStyleSheet(f"color:{GREEN if ok else RED};font-size:11px;font-weight:600;")
        self.status.setText(text)

    def _save_receipt(self) -> bool:
        v = self._receipt_values()
        err = self._validate_receipt(v) or self._validate_pickup_conflict()
        if err:
            QMessageBox.warning(self, "Receipt printer", err)
            return False
        set_many(v)
        self._clean_r = self._receipt_state()
        return True

    def _validate_pickup_conflict(self) -> str:
        """Receipt printer must not equal the pickup printer on screen."""
        p = self.p_printer.currentText().strip()
        rec = self.r_printer.currentText().strip()
        if self.p_enabled.isChecked() and p and rec and p.lower() == rec.lower():
            return "The receipt printer is the same as the pickup printer. Choose a different one."
        return ""

    def _save_pickup(self) -> bool:
        v = self._pickup_values()
        err = self._validate_pickup(v)
        if err:
            QMessageBox.warning(self, "Pickup printer", err)
            return False
        set_many(v)
        self._clean_p = self._pickup_state()
        return True

    def _save(self) -> bool:
        r, p = self._receipt_values(), self._pickup_values()
        err = self._validate_receipt(r) or self._validate_pickup(p)
        if err:
            QMessageBox.warning(self, "Printer setup", err)
            self._say("Not saved — " + err, ok=False)
            return False
        set_many({**r, **p})
        self._clean_r, self._clean_p = self._receipt_state(), self._pickup_state()
        self._say("✓  Printer setup saved.")
        return True

    def _test_receipt(self):
        if not self._save_receipt():
            return
        try:
            from utils.print_manager import print_test_receipt
            print_test_receipt(self, "sale")
            self._say("✓  Test receipt sent to the receipt printer.")
        except Exception as e:
            QMessageBox.warning(self, "Receipt printer", f"Could not print: {e}")

    def _test_pickup(self):
        if not self.p_printer.currentText().strip():
            QMessageBox.warning(self, "Pickup printer", "Choose a printer first.")
            return
        if not self._save_pickup():
            return
        try:
            from utils.print_manager import print_pickup
            print_pickup(PT.sample_receipt(), test=True)
            self._say("✓  Test ticket sent to the pickup printer.")
        except Exception as e:
            QMessageBox.warning(self, "Pickup printer", f"Could not print: {e}")
