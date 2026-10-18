"""
Receipt designer tab (Manager window).

Left: the settings, in three groups —
    Printer (this PC)  : printer type profile, Windows queue, print mode, ESC/POS, cutter
    Paper & feed       : paper width, columns, left margin, paper fed after printing, form feed
    Receipt content    : which header lines show, extra header/footer lines, divider style
Right: a live preview built by the same code that prints, using the UNSAVED settings.

Printer settings belong to this PC; the content settings are the receipt's look
(see utils/receipt_layout.py). Export/import moves a whole setup between PCs.
"""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                             QComboBox, QSpinBox, QPlainTextEdit, QScrollArea, QMessageBox,
                             QFileDialog, QDialog, QDialogButtonBox, QSizePolicy)

from ui.shared.checkbox import make_checkbox
from ui.shared.theme import (AMBER, AMBER_DARK, DARK, DARK_CARD, WARM_WHITE,
                             WHITE, BORDER, MUTED, RED, GREEN)
AMBER_TEXT_ON_WHITE = "#8a5510"      # same value the Manager window uses (not part of the theme)
from utils import receipt_layout as RL
from utils import receipt_samples as RS
from utils import receipt_setup_io as IO
from utils.printer_capabilities import (STANDARD_WIDTHS_MM, columns_for_width_mm,
                                        detect_reported_width_mm, list_print_queues,
                                        check_queue, PLAUSIBLE_RECEIPT_MM)
from utils.printer_profiles import PROFILES, get_profile, matching_profile

LABELS = {
    "receipt_printer_name": "Windows printer", "receipt_printer_mode": "Print mode",
    "receipt_paper_width_mm": "Paper width (mm)", "receipt_columns": "Columns",
    "receipt_left_margin": "Left margin", "receipt_feed_lines": "Paper feed after receipt",
    "receipt_form_feed": "Form feed", "receipt_printer_escpos": "ESC/POS formatting",
    "receipt_printer_has_cutter": "Automatic cutter", "cash_drawer_kick_on_cash_sale": "Cash drawer",
    "receipt_copies": "Copies", "receipt_show_address": "Show address",
    "receipt_show_phone": "Show phone", "receipt_show_trn": "Show TRN",
    "receipt_show_cashier": "Show cashier", "receipt_header_extra": "Extra header lines",
    "receipt_footer_extra": "Extra footer lines", "receipt_divider": "Divider character",
}
BUSINESS_LABELS = {"name": "Business name", "address": "Address", "phone": "Phone",
                   "tax_id": "TRN", "receipt_footer": "Footer message"}


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setStyleSheet(f"QFrame#card{{background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;}}")
    box.setObjectName("card")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(8)
    h = QLabel(title.upper())
    h.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;border:none;")
    lay.addWidget(h)
    return box, lay


def _lbl(text: str, bold: bool = True) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{DARK_CARD};font-size:12px;{'font-weight:600;' if bold else ''}border:none;")
    return l


def _hint(text: str) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setStyleSheet(f"color:{MUTED};font-size:11px;border:none;")
    return l


_INPUT = (f"background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:6px;"
          f"padding:3px 8px;font-size:12px;")


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setStyleSheet(f"QPushButton{{background:{AMBER};color:{DARK};border:none;border-radius:7px;"
                        f"padding:8px 16px;font-size:12px;font-weight:700;}}"
                        f"QPushButton:hover{{background:{AMBER_DARK};}}")
    else:
        b.setStyleSheet(f"QPushButton{{background:{WHITE};color:{DARK_CARD};border:1.5px solid {AMBER};"
                        f"border-radius:7px;padding:7px 12px;font-size:12px;font-weight:600;}}"
                        f"QPushButton:hover{{background:{AMBER};color:{DARK};}}")
    return b


class ReceiptDesignerTab(QWidget):
    saved = pyqtSignal()        # settings were written (the window refreshes other panels)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = True
        self._dirty = False
        self._build()
        self.load_from_db()
        self._loading = False
        self._render_preview()
        self._update_printer_check()

    # ══════════════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════════════
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- left: settings (scrolls) ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        inner = QWidget()
        inner.setStyleSheet(f"background:{WHITE};")
        left = QVBoxLayout(inner)
        left.setContentsMargins(20, 18, 14, 18)
        left.setSpacing(12)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(430)
        root.addWidget(scroll, stretch=5)

        # ---- Printer ----
        box, bl = _card("Printer (this PC)")
        bl.addWidget(_lbl("Printer type"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Choose a printer type to fill in suggested values…", None)
        for p in PROFILES:
            self.profile_combo.addItem(p["name"], p["id"])
        self.profile_combo.setStyleSheet(_INPUT)
        self.profile_combo.activated.connect(self._on_profile)
        bl.addWidget(self.profile_combo)
        self.profile_note = _hint("")
        bl.addWidget(self.profile_note)

        bl.addWidget(_lbl("Windows printer"))
        row = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.printer_combo.setEditable(True)
        self.printer_combo.setStyleSheet(_INPUT)
        self.printer_combo.lineEdit().setPlaceholderText("Leave blank to use the Windows default printer…")
        refresh = _btn("↻")
        refresh.setFixedWidth(36)
        refresh.setToolTip("Refresh printer list")
        refresh.clicked.connect(self._refresh_queues)
        row.addWidget(self.printer_combo, stretch=1)
        row.addWidget(refresh)
        bl.addLayout(row)
        self.check_lbl = QLabel("")
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.check_lbl.setStyleSheet("border:none;font-size:11px;")
        bl.addWidget(self.check_lbl)

        bl.addWidget(_lbl("Print mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Raw — plain text / ESC/POS straight to the printer", "raw")
        self.mode_combo.addItem("Raster — graphics through the Windows driver", "raster")
        self.mode_combo.setStyleSheet(_INPUT)
        bl.addWidget(self.mode_combo)
        self.escpos_cb = make_checkbox("Send ESC/POS formatting (bold, double-size totals)", False)
        self.cutter_cb = make_checkbox("Printer has an automatic paper cutter", True)
        bl.addWidget(self.escpos_cb)
        bl.addWidget(self.cutter_cb)
        left.addWidget(box)

        # ---- Paper & feed ----
        box, bl = _card("Paper & feed (this PC)")
        bl.addWidget(_lbl("Paper width"))
        row = QHBoxLayout()
        self.width_combo = QComboBox()
        for mm in STANDARD_WIDTHS_MM:
            self.width_combo.addItem(f"{mm} mm", mm)
        self.width_combo.setStyleSheet(_INPUT)
        detect = _btn("Detect")
        detect.clicked.connect(self._detect_width)
        row.addWidget(self.width_combo, stretch=1)
        row.addWidget(detect)
        bl.addLayout(row)
        self.detect_lbl = _hint("")
        bl.addWidget(self.detect_lbl)

        grid = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(_lbl("Columns"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(0, 80)
        self.cols_spin.setSpecialValueText("Auto")
        self.cols_spin.setStyleSheet(_INPUT)
        col.addWidget(self.cols_spin)
        grid.addLayout(col)
        col = QVBoxLayout()
        col.addWidget(_lbl("Left margin"))
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 10)
        self.margin_spin.setSuffix(" col")
        self.margin_spin.setStyleSheet(_INPUT)
        col.addWidget(self.margin_spin)
        grid.addLayout(col)
        bl.addLayout(grid)
        self.cols_hint = _hint("")
        bl.addWidget(self.cols_hint)

        self.feed_cb = make_checkbox("Set the paper fed after each receipt", False)
        bl.addWidget(self.feed_cb)
        row = QHBoxLayout()
        self.feed_spin = QSpinBox()
        self.feed_spin.setRange(0, 20)
        self.feed_spin.setSuffix(" blank lines")
        self.feed_spin.setStyleSheet(_INPUT)
        row.addWidget(self.feed_spin)
        row.addStretch()
        bl.addLayout(row)
        bl.addWidget(_hint("Unticked keeps the standard 2 blank lines. Enough lines push the last "
                           "line past the tear bar; the calibration wizard finds the right number."))
        self.ff_cb = make_checkbox("End plain-text jobs with a form feed", True)
        bl.addWidget(self.ff_cb)
        cal = _btn("Calibrate printer…")
        cal.clicked.connect(self._calibrate)
        bl.addWidget(cal)
        left.addWidget(box)

        # ---- Content ----
        box, bl = _card("Receipt content (same on every terminal)")
        self.addr_cb = make_checkbox("Show address", True)
        self.phone_cb = make_checkbox("Show phone number", True)
        self.trn_cb = make_checkbox("Show TRN", True)
        self.cashier_cb = make_checkbox("Show cashier on sale receipts", True)
        for cb in (self.addr_cb, self.phone_cb, self.trn_cb, self.cashier_cb):
            bl.addWidget(cb)
        bl.addWidget(_lbl("Extra header lines (under the business details)"))
        self.header_edit = QPlainTextEdit()
        self.header_edit.setFixedHeight(64)
        self.header_edit.setPlaceholderText("One line per row, up to 4 lines")
        self.header_edit.setStyleSheet(_INPUT)
        bl.addWidget(self.header_edit)
        bl.addWidget(_lbl("Extra footer lines (under the footer message)"))
        self.footer_edit = QPlainTextEdit()
        self.footer_edit.setFixedHeight(64)
        self.footer_edit.setPlaceholderText("One line per row, up to 4 lines")
        self.footer_edit.setStyleSheet(_INPUT)
        bl.addWidget(self.footer_edit)
        bl.addWidget(_hint("The main footer message is edited under Business → Business info."))
        bl.addWidget(_lbl("Divider character"))
        self.div_combo = QComboBox()
        for ch in RL.DIVIDER_CHOICES:
            self.div_combo.addItem(f"{ch * 12}", ch)
        self.div_combo.setStyleSheet(_INPUT)
        bl.addWidget(self.div_combo)
        left.addWidget(box)
        left.addStretch()

        # ---- right: preview + actions ----
        right = QWidget()
        right.setStyleSheet(f"background:{WARM_WHITE};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 18, 20, 18)
        rl.setSpacing(10)
        root.addWidget(right, stretch=4)

        top = QHBoxLayout()
        top.addWidget(_lbl("Preview"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Sale receipt", "sale")
        self.kind_combo.addItem("Void notice", "void")
        self.kind_combo.addItem("Refund receipt", "refund")
        self.kind_combo.setStyleSheet(_INPUT)
        top.addWidget(self.kind_combo)
        top.addStretch()
        rl.addLayout(top)
        self.preview_info = _hint("")
        rl.addWidget(self.preview_info)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(10)
        self.ruler = QLabel("")
        self.ruler.setFont(mono)
        self.ruler.setStyleSheet(f"color:{MUTED};background:{WHITE};padding:4px 10px 0 10px;"
                                 f"border:1px solid {BORDER};border-bottom:none;")
        rl.addWidget(self.ruler)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(mono)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setStyleSheet(f"background:{WHITE};color:#111;border:1px solid {BORDER};padding:4px 10px;")
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rl.addWidget(self.preview, stretch=1)

        self.code_lbl = _hint("")
        rl.addWidget(self.code_lbl)
        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")
        rl.addWidget(self.feedback)

        r1 = QHBoxLayout()
        self.save_btn = _btn("Save", primary=True)
        self.save_btn.clicked.connect(self.save)
        test = _btn("Print test receipt")
        test.clicked.connect(self._print_test)
        r1.addWidget(self.save_btn)
        r1.addWidget(test)
        r1.addStretch()
        rl.addLayout(r1)
        r2 = QHBoxLayout()
        for text, fn in (("Export setup…", self._export), ("Import setup…", self._import),
                         ("Reset layout", self._reset_layout)):
            b = _btn(text)
            b.clicked.connect(fn)
            r2.addWidget(b)
        r2.addStretch()
        rl.addLayout(r2)

        # ---- wiring: anything that changes the receipt re-renders the preview ----
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._render_preview)
        for sig in (self.mode_combo.currentIndexChanged, self.width_combo.currentIndexChanged,
                    self.cols_spin.valueChanged, self.margin_spin.valueChanged,
                    self.feed_spin.valueChanged, self.div_combo.currentIndexChanged,
                    self.printer_combo.currentTextChanged, self.header_edit.textChanged,
                    self.footer_edit.textChanged):
            sig.connect(self._changed)
        for cb in (self.escpos_cb, self.cutter_cb, self.feed_cb, self.ff_cb, self.addr_cb,
                   self.phone_cb, self.trn_cb, self.cashier_cb):
            cb.toggled.connect(self._changed)
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._timer.start())
        self.feed_cb.toggled.connect(lambda on: self.feed_spin.setEnabled(on))
        self.mode_combo.currentIndexChanged.connect(self._update_printer_check)
        self.printer_combo.currentTextChanged.connect(lambda _t: self._update_printer_check())

    # ══════════════════════════════════════════════════════════════════
    # Values <-> widgets
    # ══════════════════════════════════════════════════════════════════
    def _collect(self) -> dict[str, str]:
        """All settings, taking the on-screen values (unsaved) over the saved ones."""
        v = IO.current_values()                      # keeps copies / cash-drawer which live elsewhere
        v.update({
            "receipt_printer_name": self.printer_combo.currentText().strip(),
            "receipt_printer_mode": self.mode_combo.currentData(),
            "receipt_paper_width_mm": str(self.width_combo.currentData()),
            "receipt_columns": "" if self.cols_spin.value() == 0 else str(self.cols_spin.value()),
            "receipt_left_margin": str(self.margin_spin.value()),
            "receipt_feed_lines": str(self.feed_spin.value()) if self.feed_cb.isChecked() else "",
            "receipt_form_feed": "1" if self.ff_cb.isChecked() else "0",
            "receipt_printer_escpos": "1" if self.escpos_cb.isChecked() else "0",
            "receipt_printer_has_cutter": "1" if self.cutter_cb.isChecked() else "0",
            "receipt_show_address": "1" if self.addr_cb.isChecked() else "0",
            "receipt_show_phone": "1" if self.phone_cb.isChecked() else "0",
            "receipt_show_trn": "1" if self.trn_cb.isChecked() else "0",
            "receipt_show_cashier": "1" if self.cashier_cb.isChecked() else "0",
            "receipt_header_extra": self.header_edit.toPlainText().rstrip(),
            "receipt_footer_extra": self.footer_edit.toPlainText().rstrip(),
            "receipt_divider": self.div_combo.currentData(),
        })
        return v

    def _apply_values(self, v: dict[str, str]):
        """Show a settings dict in the controls (without marking anything changed)."""
        was = self._loading
        self._loading = True
        try:
            def g(k):
                return v.get(k, RL.HARDWARE_DEFAULTS.get(k, RL.SHARED_DEFAULTS.get(k, "")))
            self.printer_combo.setEditText(g("receipt_printer_name"))
            self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(g("receipt_printer_mode"))))
            try:
                mm = int(float(g("receipt_paper_width_mm") or 76))
            except ValueError:
                mm = 76
            closest = min(STANDARD_WIDTHS_MM, key=lambda s: abs(s - mm))
            self.width_combo.setCurrentIndex(max(0, self.width_combo.findData(closest)))
            ok, c, _ = RL.validate_value("receipt_columns", g("receipt_columns"))
            self.cols_spin.setValue(int(c) if ok and c else 0)
            ok, m, _ = RL.validate_value("receipt_left_margin", g("receipt_left_margin"))
            self.margin_spin.setValue(int(m) if ok and m else 0)
            ok, f, _ = RL.validate_value("receipt_feed_lines", g("receipt_feed_lines"))
            self.feed_cb.setChecked(bool(ok and f != ""))
            self.feed_spin.setValue(int(f) if ok and f != "" else 2)
            self.feed_spin.setEnabled(self.feed_cb.isChecked())
            self.ff_cb.setChecked(g("receipt_form_feed") != "0")
            self.escpos_cb.setChecked(g("receipt_printer_escpos") == "1")
            self.cutter_cb.setChecked(g("receipt_printer_has_cutter") != "0")
            self.addr_cb.setChecked(g("receipt_show_address") != "0")
            self.phone_cb.setChecked(g("receipt_show_phone") != "0")
            self.trn_cb.setChecked(g("receipt_show_trn") != "0")
            self.cashier_cb.setChecked(g("receipt_show_cashier") != "0")
            self.header_edit.setPlainText(g("receipt_header_extra"))
            self.footer_edit.setPlainText(g("receipt_footer_extra"))
            self.div_combo.setCurrentIndex(max(0, self.div_combo.findData(g("receipt_divider"))))
            pid = matching_profile(v)
            self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(pid)) if pid else 0)
            self.profile_note.setText("" if not pid else get_profile(pid)["description"])
        finally:
            self._loading = was

    def load_from_db(self):
        self._refresh_queues(keep_text=False)
        self._apply_values(IO.current_values())
        self._dirty = False
        self._update_code()
        if not self._loading:
            self._render_preview()
            self._update_printer_check()

    def reload_if_clean(self):
        """Refresher for when the tab is shown again: pick up changes made
        elsewhere (the Business tab's printer panel), unless there are edits here."""
        if not self._dirty:
            self.load_from_db()

    # ══════════════════════════════════════════════════════════════════
    # Behaviour
    # ══════════════════════════════════════════════════════════════════
    def _changed(self, *_):
        if self._loading:
            return
        self._dirty = True
        self.feedback.setText("Unsaved changes")
        self.feedback.setStyleSheet(f"color:{AMBER_TEXT_ON_WHITE};font-size:11px;font-weight:600;")
        self._timer.start()

    def _render_preview(self):
        vals = self._collect()
        try:
            from utils.print_manager import _get_biz_and_currency
            biz, currency = _get_biz_and_currency()      # same business details + currency the print path uses
            with RL.use_layout(vals):
                lines = RL.finalize_lines(RS.preview_lines(self.kind_combo.currentData(), biz, currency))
            lay = RL.layout_from_values(vals)
            self.preview.setPlainText("\n".join(t for t, _k in lines))
            ruler = "".join(str((i // 10) % 10) if i % 10 == 0 else ("·" if i % 5 == 0 else "-")
                            for i in range(1, lay.columns + 1))
            self.ruler.setText(ruler)
            fold = RL.fold_target_from_values(vals)
            self.preview_info.setText(
                f"{lay.columns} columns on the paper · {lay.width} for text"
                + (f" · characters folded to {fold.upper()}" if fold else " · full character set (raster)"))
        except Exception as e:                       # a preview problem must not break the tab
            self.preview.setPlainText(f"(preview unavailable: {e})")

    def _update_code(self):
        self.code_lbl.setText(f"Setup code: <b>{RL.setup_code(IO.current_values())}</b> — "
                              "two PCs with the same code are configured identically.")
        self.code_lbl.setTextFormat(Qt.TextFormat.RichText)
        cols = columns_for_width_mm(self.width_combo.currentData())
        self.cols_hint.setText(f"Auto = {cols} columns for {self.width_combo.currentData()} mm paper.")

    def _on_profile(self, index: int):
        pid = self.profile_combo.itemData(index)
        if not pid:
            return
        p = get_profile(pid)
        v = self._collect()
        v.update(p["values"])
        self._apply_values(v)
        self.profile_combo.setCurrentIndex(index)
        self.profile_note.setText(p["description"])
        self._changed()

    def _refresh_queues(self, *_a, keep_text: bool = True):
        cur = self.printer_combo.currentText() if keep_text else ""
        was = self._loading
        self._loading = True
        try:
            self.printer_combo.clear()
            self._queues = list_print_queues()
            for q in self._queues:
                self.printer_combo.addItem(q["name"])
            self.printer_combo.setEditText(cur)
        finally:
            self._loading = was
        self._update_printer_check()

    def _update_printer_check(self):
        if not hasattr(self, "check_lbl"):
            return
        colors = {"ok": GREEN, "info": MUTED, "warn": "#B45309"}
        icon = {"ok": "✓", "info": "•", "warn": "⚠"}
        notes = check_queue(self.printer_combo.currentText(), self.mode_combo.currentData() or "raw",
                            getattr(self, "_queues", None))
        self.check_lbl.setText("<br>".join(
            f"<span style='color:{colors[s]};'>{icon[s]} {t}</span>" for s, t in notes))

    def _detect_width(self):
        name = self.printer_combo.currentText().strip()
        mm = detect_reported_width_mm(name)
        lo, hi = PLAUSIBLE_RECEIPT_MM
        if mm is None:
            msg = "Couldn't read a paper width from the driver — choose it manually."
        elif not (lo <= mm <= hi):
            msg = (f"The driver reports {mm} mm, which isn't a receipt width (a Generic / Text Only "
                   f"queue left on Letter, A4 or B4 does this). Choose the width manually.")
        else:
            closest = min(STANDARD_WIDTHS_MM, key=lambda s: abs(s - mm))
            self.width_combo.setCurrentIndex(self.width_combo.findData(closest))
            msg = f"Driver reports {mm} mm — set to {closest} mm."
        self.detect_lbl.setText(msg)

    def _validate(self, vals: dict[str, str]) -> list[str]:
        errs = []
        for k in RL.SPEC:
            ok, _n, e = RL.validate_value(k, vals.get(k, ""))
            if not ok:
                errs.append(f"{LABELS.get(k, k)}: {e}")
        cols = RL.columns_from_settings(vals.get("receipt_paper_width_mm", "76"),
                                        vals.get("receipt_columns", ""))
        try:
            if int(vals.get("receipt_left_margin") or 0) > cols - 16:
                errs.append("Left margin: leaves fewer than 16 columns for text")
        except ValueError:
            pass
        return errs

    def save(self) -> bool:
        vals = self._collect()
        errs = self._validate(vals)
        if errs:
            self._say("Not saved — " + "; ".join(errs), error=True)
            return False
        try:
            from core.db_config import apply_setup
            apply_setup({k: RL.validate_value(k, vals[k])[1] for k in RL.SPEC})
        except Exception as e:
            self._say(f"Could not save: {e}", error=True)
            return False
        self._dirty = False
        self._update_code()
        self._say("✓  Saved.", error=False)
        self.saved.emit()
        return True

    def _say(self, text: str, error: bool):
        self.feedback.setText(text)
        self.feedback.setStyleSheet(f"color:{RED if error else GREEN};font-size:11px;font-weight:600;")

    def _ensure_saved(self, why: str) -> bool:
        if not self._dirty:
            return True
        btn = QMessageBox.question(self, "Save first?",
                                   f"{why} uses the SAVED settings. Save your changes now?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        return btn == QMessageBox.StandardButton.Yes and self.save()

    def _print_test(self):
        if not self._ensure_saved("The test receipt"):
            return
        from utils.print_manager import print_test_receipt
        print_test_receipt(self)

    def _calibrate(self):
        if not self._ensure_saved("Calibration"):
            return
        from ui.manager.calibration_dialog import CalibrationDialog
        v = self._collect()
        dlg = CalibrationDialog(self, RL.layout_from_values(v).columns,
                                v["receipt_printer_has_cutter"] == "1", v["receipt_printer_mode"])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = dlg.results()
        if not res:
            return
        if "receipt_columns" in res:
            self.cols_spin.setValue(int(res["receipt_columns"]))
        if "receipt_feed_lines" in res:
            self.feed_cb.setChecked(True)
            self.feed_spin.setValue(int(res["receipt_feed_lines"]))
        self._say("Calibration results applied — check the preview, then Save.", error=False)

    def _reset_layout(self):
        if QMessageBox.question(self, "Reset layout",
                                "Reset columns, margin, paper feed, form feed and the receipt content "
                                "options to the standard receipt? (Printer, mode and paper width stay.)",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                                ) != QMessageBox.StandardButton.Yes:
            return
        v = self._collect()
        for k in ("receipt_columns", "receipt_left_margin", "receipt_feed_lines", "receipt_form_feed"):
            v[k] = RL.HARDWARE_DEFAULTS[k]
        v.update(RL.SHARED_DEFAULTS)
        self._apply_values(v)
        self._changed()

    # ── export / import ─────────────────────────────────────────────────
    def _export(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Export setup")
        lay = QVBoxLayout(dlg)
        lay.addWidget(_lbl("What should the file contain?"))
        hw = make_checkbox("Printer settings (paper width, feed, margin, cutter, mode…)", True)
        nm = make_checkbox("The Windows printer name (differs from PC to PC — usually leave off)", False)
        bz = make_checkbox("Business details (name, address, phone, TRN, footer)", False)
        for w in (hw, nm, bz):
            lay.addWidget(w)
        lay.addWidget(_hint("Receipt content settings are always included. Database settings and "
                            "passwords are never exported."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path, _f = QFileDialog.getSaveFileName(self, "Export receipt setup", "receipt-setup.json",
                                               "Receipt setup (*.json)")
        if not path:
            return
        try:
            from core.db_config import get_business
            doc = IO.export_setup(self._collect(), include_hardware=hw.isChecked(),
                                  include_printer_name=nm.isChecked(),
                                  business=get_business() if bz.isChecked() else None)
            with open(path, "w", encoding="utf-8") as f:
                f.write(IO.dumps(doc))
            self._say(f"✓  Exported to {os.path.basename(path)}", error=False)
        except Exception as e:
            self._say(f"Could not export: {e}", error=True)

    def _import(self):
        path, _f = QFileDialog.getOpenFileName(self, "Import receipt setup", "", "Receipt setup (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            self._say(f"Could not read the file: {e}", error=True)
            return
        self.import_text(text)

    def import_text(self, text: str, confirm=None) -> bool:
        """Validate → show what would change → apply all-or-nothing. `confirm`
        (a callable taking the summary text) replaces the dialog in tests."""
        from core.db_config import get_business
        plan = IO.plan_import(text, IO.current_values(), get_business())
        if plan.errors:
            QMessageBox.warning(self, "Can't import this file",
                                "Nothing was changed.\n\n" + "\n".join(f"• {e}" for e in plan.errors))
            return False
        if not (plan.changes or plan.business_changes):
            QMessageBox.information(self, "Import", "This setup matches the current one — nothing to change.")
            return False
        rows = [f"• {LABELS.get(k, k)}:  {o or '(none)'}  →  {n or '(none)'}" for k, o, n in plan.changes]
        rows += [f"• {BUSINESS_LABELS.get(k, k)}:  {o or '(none)'}  →  {n}" for k, o, n in plan.business_changes]
        if plan.skipped:
            rows.append("\nIgnored (not understood by this version): " + ", ".join(k for k, _r in plan.skipped))
        summary = ("These settings will change:\n\n" + "\n".join(rows)
                   + ("\n\nYour unsaved edits on this tab will be replaced." if self._dirty else ""))
        if confirm is not None:
            go = confirm(summary)
        else:
            go = QMessageBox.question(self, "Import setup", summary,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                                      ) == QMessageBox.StandardButton.Yes
        if not go:
            return False
        try:
            IO.apply_plan(plan)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", f"Nothing was changed.\n\n{e}")
            return False
        self.load_from_db()
        self._say("✓  Setup imported.", error=False)
        self.saved.emit()
        return True
