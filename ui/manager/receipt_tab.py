"""
Receipt designer tab (Manager window).

Left: the everyday settings —
    Printer (this PC)  : printer type profile, Windows queue, print mode, cash drawer, copies
    Paper (this PC)    : paper width, Calibrate printer, and the "Advanced settings" button
    Receipt content    : which header lines show, extra header/footer lines, divider style
Advanced settings (pop-up, non-modal so the preview stays visible):
    Printer commands   : ESC/POS formatting, automatic cutter
    Text size          : ESC/POS font (A/B), business-name and TOTAL size, graphics-mode font size
    Paper tuning       : columns, left margin, paper fed after printing, form feed
    Backup & restore   : export / import / reset
Right: a live preview built by the same code that prints, using the UNSAVED settings.

Printer settings belong to this PC; the content settings are the receipt's look
(see utils/receipt_layout.py). Export/import moves a whole setup between PCs.
"""
from __future__ import annotations

import html
import json
import os

from PyQt6.QtCore import Qt, QTimer, QSettings, QPoint, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                             QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QScrollArea, QMessageBox,
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
    "receipt_font": "Text size (font)", "receipt_raster_font_pt": "Graphics-mode font size",
    "receipt_heading_size": "Business name size", "receipt_total_size": "TOTAL line size",
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
        self.drawer_cb = make_checkbox("Open the cash drawer on cash / split-tender sales", False)
        bl.addWidget(self.drawer_cb)
        bl.addWidget(_hint("The drawer must be plugged into the receipt printer. It opens with its own "
                           "short command, so it works in Raw and Raster mode, with or without "
                           "ESC/POS formatting."))
        bl.addWidget(_lbl("Copies per sale"))
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 5)
        self.copies_spin.setStyleSheet(_INPUT)
        bl.addWidget(self.copies_spin)
        left.addWidget(box)

        # ---- Paper & feed ----
        box, bl = _card("Paper (this PC)")
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

        cal = _btn("Calibrate printer…")
        cal.clicked.connect(self._calibrate)
        bl.addWidget(cal)

        # Columns, margin, paper feed and form feed live in a pop-up: the calibration
        # wizard normally sets them, so they are rarely edited by hand. The widgets are
        # ordinary attributes of this tab, so saving/loading/preview/profiles are unchanged.
        self._build_advanced_dialog()
        self.adv_btn = _btn("⚙  Advanced settings…")
        self.adv_btn.clicked.connect(self._open_advanced)
        bl.addWidget(self.adv_btn)
        self.adv_summary = _hint("")
        bl.addWidget(self.adv_summary)
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
        self.kind_combo.addItem("Report — full Z-report", "report_full")
        self.kind_combo.addItem("Report — product summary", "report_products")
        self.kind_combo.addItem("Report — session summary", "report_summary")
        self.kind_combo.setStyleSheet(_INPUT)
        top.addWidget(self.kind_combo)
        top.addStretch()
        top.addWidget(_hint("Preview size"))
        self.zoom_out = _btn("A−")
        self.zoom_in = _btn("A+")
        for b in (self.zoom_out, self.zoom_in):
            b.setFixedWidth(40)
        self.zoom_out.setToolTip("Smaller preview text (only the on-screen preview, not the printed receipt)")
        self.zoom_in.setToolTip("Larger preview text (only the on-screen preview, not the printed receipt)")
        self.zoom_out.clicked.connect(lambda: self._zoom(-1))
        self.zoom_in.clicked.connect(lambda: self._zoom(+1))
        top.addWidget(self.zoom_out)
        top.addWidget(self.zoom_in)
        rl.addLayout(top)
        self.preview_info = _hint("")
        rl.addWidget(self.preview_info)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._mono = QFont(mono)
        try:                                   # the on-screen preview size is remembered on this PC
            self._preview_pt = max(7, min(16, int(QSettings("POS", "ReceiptDesigner").value("preview_pt", 10))))
        except (TypeError, ValueError):
            self._preview_pt = 10
        mono.setPointSize(self._preview_pt)
        self.ruler = QLabel("")
        self.ruler.setFont(mono)
        self.ruler.setStyleSheet(self._ruler_css(self._preview_pt))
        rl.addWidget(self.ruler)
        self.preview = QTextEdit()             # rich text, so the chosen sizes show in the preview
        self.preview.setReadOnly(True)
        self.preview.setFont(mono)
        self.preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.preview.setStyleSheet(self._preview_css(self._preview_pt))
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
        self.test_btn = _btn("Print test receipt")
        self.test_btn.clicked.connect(self._print_test)
        r1.addWidget(self.save_btn)
        r1.addWidget(self.test_btn)
        r1.addStretch()
        rl.addLayout(r1)

        # ---- wiring: anything that changes the receipt re-renders the preview ----
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._render_preview)
        for sig in (self.font_combo.currentIndexChanged, self.heading_combo.currentIndexChanged,
                    self.total_combo.currentIndexChanged, self.raster_pt_spin.valueChanged,
                    self.mode_combo.currentIndexChanged, self.width_combo.currentIndexChanged,
                    self.cols_spin.valueChanged, self.margin_spin.valueChanged,
                    self.feed_spin.valueChanged, self.div_combo.currentIndexChanged,
                    self.printer_combo.currentTextChanged, self.header_edit.textChanged,
                    self.footer_edit.textChanged, self.copies_spin.valueChanged):
            sig.connect(self._changed)
        for sig in (self.cols_spin.valueChanged, self.margin_spin.valueChanged,
                    self.feed_spin.valueChanged, self.feed_cb.toggled, self.ff_cb.toggled,
                    self.escpos_cb.toggled, self.cutter_cb.toggled, self.mode_combo.currentIndexChanged,
                    self.font_combo.currentIndexChanged, self.heading_combo.currentIndexChanged,
                    self.total_combo.currentIndexChanged, self.raster_pt_spin.valueChanged):
            sig.connect(self._update_adv_summary)
        for cb in (self.escpos_cb, self.cutter_cb, self.drawer_cb, self.feed_cb, self.ff_cb,
                   self.addr_cb, self.phone_cb, self.trn_cb, self.cashier_cb):
            cb.toggled.connect(self._changed)
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._timer.start())
        self.kind_combo.currentIndexChanged.connect(lambda _i: self._update_test_label())
        self.feed_cb.toggled.connect(lambda on: self.feed_spin.setEnabled(on))
        self.mode_combo.currentIndexChanged.connect(self._update_printer_check)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._update_size_controls())
        self.escpos_cb.toggled.connect(lambda _on: self._update_size_controls())
        self.font_combo.currentIndexChanged.connect(lambda _i: self._update_size_controls())
        self.heading_combo.currentIndexChanged.connect(lambda _i: self._update_size_controls())
        self.printer_combo.currentTextChanged.connect(lambda _t: self._update_printer_check())

    # ══════════════════════════════════════════════════════════════════
    # Values <-> widgets
    # ══════════════════════════════════════════════════════════════════
    def _collect(self) -> dict[str, str]:
        """All settings, taking the on-screen values (unsaved) over the saved ones."""
        v = IO.current_values()                      # start from the saved values
        v.update({
            "receipt_copies": str(self.copies_spin.value()),
            "cash_drawer_kick_on_cash_sale": "1" if self.drawer_cb.isChecked() else "0",
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
            "receipt_font": self.font_combo.currentData(),
            "receipt_heading_size": self.heading_combo.currentData(),
            "receipt_total_size": self.total_combo.currentData(),
            "receipt_raster_font_pt": "" if self.raster_pt_spin.value() == self.raster_pt_spin.minimum()
                                      else str(self.raster_pt_spin.value()),
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
            self.drawer_cb.setChecked(g("cash_drawer_kick_on_cash_sale") == "1")
            ok, n, _ = RL.validate_value("receipt_copies", g("receipt_copies"))
            self.copies_spin.setValue(int(n) if ok and n else 1)
            self.addr_cb.setChecked(g("receipt_show_address") != "0")
            self.phone_cb.setChecked(g("receipt_show_phone") != "0")
            self.trn_cb.setChecked(g("receipt_show_trn") != "0")
            self.cashier_cb.setChecked(g("receipt_show_cashier") != "0")
            self.header_edit.setPlainText(g("receipt_header_extra"))
            self.footer_edit.setPlainText(g("receipt_footer_extra"))
            self.div_combo.setCurrentIndex(max(0, self.div_combo.findData(g("receipt_divider"))))
            self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(g("receipt_font"))))
            self.heading_combo.setCurrentIndex(max(0, self.heading_combo.findData(g("receipt_heading_size"))))
            self.total_combo.setCurrentIndex(max(0, self.total_combo.findData(g("receipt_total_size"))))
            ok, pt, _ = RL.validate_value("receipt_raster_font_pt", g("receipt_raster_font_pt"))
            self.raster_pt_spin.setValue(int(pt) if ok and pt else self.raster_pt_spin.minimum())
            pid = matching_profile(v)
            self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(pid)) if pid else 0)
            self.profile_note.setText("" if not pid else get_profile(pid)["description"])
        finally:
            self._loading = was
        self._update_size_controls()
        self._update_adv_summary()

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
            # Font B glyphs are narrower than Font A's, so the preview shrinks with it.
            pt = self._preview_pt * (0.75 if lay.font == "b" else 1.0)
            self._apply_preview_font(pt)
            self.preview.setHtml(self._lines_html(lines, lay, pt))
            ruler = "".join(str((i // 10) % 10) if i % 10 == 0 else ("·" if i % 5 == 0 else "-")
                            for i in range(1, lay.columns + 1))
            self.ruler.setText(ruler)
            self._update_cols_hint(lay.font)
            fold = RL.fold_target_from_values(vals)
            if lay.escpos:
                sizes = (f" · Font {lay.font.upper()} · name: {lay.heading_size} · total: {lay.total_size}")
            else:
                sizes = " · the printer's own font"
            self.preview_info.setText(
                f"{lay.columns} columns on the paper · {lay.width} for text{sizes}"
                + (f" · characters folded to {fold.upper()}" if fold else " · full character set (raster)"))
        except Exception as e:                       # a preview problem must not break the tab
            self.preview.setPlainText(f"(preview unavailable: {e})")

    # The app's global stylesheet forces `QWidget { font-family: Inter/Segoe UI; font-size: 14px }`
    # on every widget, which beats QWidget.setFont() — so the preview was drawn in a big
    # PROPORTIONAL UI font (columns didn't line up, zoom did nothing). A widget's own
    # stylesheet wins over the app-wide one, so the monospace font is set there.
    _MONO_FAMILY = '"Consolas", "Courier New", "DejaVu Sans Mono", "Liberation Mono", monospace'

    def _preview_css(self, pt: float) -> str:
        return (f"background:{WHITE};color:#111;border:1px solid {BORDER};padding:4px 10px;"
                f"font-family:{self._MONO_FAMILY};font-size:{pt:.1f}pt;")

    def _ruler_css(self, pt: float) -> str:
        return (f"color:{MUTED};background:{WHITE};padding:4px 10px 0 10px;"
                f"border:1px solid {BORDER};border-bottom:none;"
                f"font-family:{self._MONO_FAMILY};font-size:{pt:.1f}pt;")

    def _apply_preview_font(self, pt: float):
        self.preview.setStyleSheet(self._preview_css(pt))
        self.ruler.setStyleSheet(self._ruler_css(pt))

    def _lines_html(self, lines, lay, pt: float) -> str:
        """The receipt as rich text, so bold and the business-name / TOTAL sizes show.
        Sizes only exist with ESC/POS; plain-text and graphics modes print one size."""
        out = []
        for text, kind in lines:
            css = "white-space:pre;margin:0;"
            if lay.escpos:
                if kind == "biz_name":
                    css += "font-weight:bold;"
                    if lay.heading_size == "double":
                        css += f"font-size:{pt * 2:.1f}pt;"          # double width AND height
                    elif lay.heading_size == "tall":
                        css += "line-height:200%;"                   # double height, same width
                elif kind == "title":
                    css += "font-weight:bold;"
                elif kind == "total":
                    css += "font-weight:bold;"
                    if lay.total_size == "tall":
                        css += "line-height:200%;"
            out.append(f'<div style="{css}">{html.escape(text) or "&nbsp;"}</div>')
        return '<html><body style="margin:0;">' + "".join(out) + "</body></html>"

    def _zoom(self, delta: int):
        """Make the ON-SCREEN preview text bigger or smaller (the printed receipt is unaffected)."""
        self._preview_pt = max(7, min(16, self._preview_pt + delta))
        QSettings("POS", "ReceiptDesigner").setValue("preview_pt", self._preview_pt)
        self._render_preview()

    def _build_advanced_dialog(self):
        """The Advanced pop-up. Non-modal on purpose: the live preview stays visible beside
        it, and every change is unsaved until Save is pressed - exactly like the main tab.
        The widgets are plain attributes of this tab (just parented here), so saving,
        loading, profiles, the calibration wizard and the preview all work unchanged."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Advanced receipt settings")
        dlg.setModal(False)
        dlg.resize(560, 700)
        dlg.setStyleSheet(f"QDialog{{background:{WHITE};}}")
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        body = QWidget()
        body.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 14, 16, 8)
        lay.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)
        lay.addWidget(_hint("Changes show in the preview straight away; press Save on the Receipt tab "
                            "to keep them. Paper tuning is normally set for you by “Calibrate printer…”."))

        # ---- Printer commands ----
        box, bl = _card("Printer commands (this PC)")
        self.escpos_cb = make_checkbox("Send ESC/POS formatting (bold business name, headings and totals)", False)
        self.cutter_cb = make_checkbox("Printer has an automatic paper cutter", True)
        bl.addWidget(self.escpos_cb)
        bl.addWidget(self.cutter_cb)
        bl.addWidget(_hint("ESC/POS unlocks bold and the text sizes below (Raw mode only). Untick the cutter "
                           "for printers that can't cut, such as dot-matrix models - a cut command sent to "
                           "them can spoil the end of the receipt."))
        lay.addWidget(box)

        # ---- Text size ----
        box, bl = _card("Text size")
        bl.addWidget(_lbl("Font"))
        self.font_combo = QComboBox()
        self.font_combo.addItem("Normal — Font A (the printer's standard)", "a")
        self.font_combo.addItem("Compact — Font B (smaller text, more columns)", "b")
        self.font_combo.setStyleSheet(_INPUT)
        bl.addWidget(self.font_combo)
        bl.addWidget(_lbl("Business name size"))
        self.heading_combo = QComboBox()
        self.heading_combo.addItem("Normal (bold)", "normal")
        self.heading_combo.addItem("Tall (double height)", "tall")
        self.heading_combo.addItem("Large (double height and width)", "double")
        self.heading_combo.setStyleSheet(_INPUT)
        bl.addWidget(self.heading_combo)
        bl.addWidget(_lbl("TOTAL line size"))
        self.total_combo = QComboBox()
        self.total_combo.addItem("Normal (bold)", "normal")
        self.total_combo.addItem("Tall (double height)", "tall")
        self.total_combo.setStyleSheet(_INPUT)
        bl.addWidget(self.total_combo)
        bl.addWidget(_lbl("Font size in graphics (raster) mode"))
        self.raster_pt_spin = QSpinBox()
        self.raster_pt_spin.setRange(4, 14)
        self.raster_pt_spin.setSpecialValueText("Auto — fit the columns")
        self.raster_pt_spin.setSuffix(" pt")
        self.raster_pt_spin.setStyleSheet(_INPUT)
        bl.addWidget(self.raster_pt_spin)
        self.size_hint = _hint("")
        bl.addWidget(self.size_hint)
        lay.addWidget(box)

        # ---- Paper tuning ----
        box, bl = _card("Paper tuning (this PC)")
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
        lay.addWidget(box)

        # ---- Backup & restore ----
        box, bl = _card("Backup & restore")
        bl.addWidget(_hint("Export this PC's receipt setup to a file, load one from another PC, or "
                           "put the layout back to the standard receipt."))
        row = QHBoxLayout()
        for text, fn in (("Export setup…", self._export), ("Import setup…", self._import),
                         ("Reset layout", self._reset_layout)):
            b = _btn(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        bl.addLayout(row)
        lay.addWidget(box)
        lay.addStretch()

        foot = QHBoxLayout()
        foot.setContentsMargins(16, 8, 16, 12)
        foot.addStretch()
        done = _btn("Done", primary=True)
        done.clicked.connect(dlg.close)
        foot.addWidget(done)
        outer.addLayout(foot)
        # never narrower than the widest control (the long ESC/POS label) + the scrollbar,
        # so nothing is ever clipped, whatever font or DPI the PC uses
        dlg.setMinimumWidth(max(480, body.minimumSizeHint().width() + 36))
        dlg.resize(max(dlg.width(), dlg.minimumWidth()), dlg.height())
        self._adv_dialog = dlg
        self._adv_placed = False

    def _open_advanced(self):
        dlg = self._adv_dialog
        if not self._adv_placed:              # first time: sit over the settings, not the preview
            try:
                top_left = self.mapToGlobal(QPoint(0, 0))
                dlg.move(top_left.x() + 24, top_left.y() + 48)
            except Exception:
                pass
            self._adv_placed = True
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _update_adv_summary(self, *_):
        """Three short lines under the button, so hidden values are never invisible."""
        if not hasattr(self, "adv_summary"):
            return
        raw = self.mode_combo.currentData() != "raster"
        esc = raw and self.escpos_cb.isChecked()
        if not raw:
            cmds, text = "graphics mode", ("graphics font auto" if self.raster_pt_spin.value() == self.raster_pt_spin.minimum()
                                           else f"graphics font {self.raster_pt_spin.value()} pt")
        elif esc:
            cmds = f"ESC/POS on · cutter {'yes' if self.cutter_cb.isChecked() else 'no'}"
            text = (f"Font {str(self.font_combo.currentData()).upper()} · name {self.heading_combo.currentData()}"
                    f" · total {self.total_combo.currentData()}")
        else:
            cmds, text = "ESC/POS off", "the printer's own font"
        cols = "auto" if self.cols_spin.value() == 0 else str(self.cols_spin.value())
        feed = f"{self.feed_spin.value()} lines" if self.feed_cb.isChecked() else "standard"
        self.adv_summary.setText(
            f"Commands: {cmds}\nText: {text}\n"
            f"Paper: columns {cols} · margin {self.margin_spin.value()} · feed {feed} · "
            f"form feed {'on' if self.ff_cb.isChecked() else 'off'}")

    def _update_size_controls(self):
        """Sizes only apply in raw mode WITH ESC/POS (the printer's own font otherwise)
        and the graphics font size only in raster mode — enable exactly what works."""
        if not hasattr(self, "size_hint"):
            return
        mode = self.mode_combo.currentData()
        esc = mode == "raw" and self.escpos_cb.isChecked()
        for w in (self.font_combo, self.heading_combo, self.total_combo):
            w.setEnabled(esc)
        self.raster_pt_spin.setEnabled(mode == "raster")
        if mode == "raster":
            msg = ("Graphics mode draws the receipt itself, so the text size follows the Columns setting "
                   "(under Paper tuning; more columns = smaller text). Or set an exact size above.")
        elif not esc:
            msg = ("Plain-text mode prints in the printer's own font, which this program can't change. "
                   "Tick “Send ESC/POS formatting” under Printer commands to choose a font and sizes.")
        else:
            msg = ("Compact (Font B) fits about ⅓ more characters per line, so the Columns change — "
                   "run the calibration wizard after switching.")
            try:
                lay = RL.layout_from_values(self._collect())
                if lay.heading_size == "double":
                    from core.db_config import get_business
                    name = (get_business().get("name") or "").strip()
                    half = max(8, lay.width // 2)
                    if len(name) > half:
                        n = -(-len(name) // half)
                        msg += (f" At “Large” the business name has {half} characters per line, so "
                                f"“{name}” prints on {n} lines — choose Tall or Normal to keep it on one.")
            except Exception:
                pass
        self.size_hint.setText(msg)

    def _update_code(self):
        self.code_lbl.setText(f"Setup code: <b>{RL.setup_code(IO.current_values())}</b> — "
                              "two PCs with the same code are configured identically.")
        self.code_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._update_cols_hint(RL.layout_from_values(self._collect()).font)

    def _update_cols_hint(self, font: str):
        """'Auto = N columns' under the Columns box (Font B fits more than Font A)."""
        cols = RL.columns_from_settings(str(self.width_combo.currentData()), "", font)
        self.cols_hint.setText(f"Auto = {cols} columns for {self.width_combo.currentData()} mm paper"
                               + (" in Font B." if font == "b" else "."))

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
        cols = RL.layout_from_values(vals).columns
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

    def _update_test_label(self):
        report = str(self.kind_combo.currentData() or "").startswith("report_")
        self.test_btn.setText("Print test report" if report else "Print test receipt")

    def _print_test(self):
        kind = self.kind_combo.currentData() or "sale"
        if not self._ensure_saved("The test report" if kind.startswith("report_") else "The test receipt"):
            return
        from utils.print_manager import print_test_receipt
        print_test_receipt(self, kind)

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
                                "Reset columns, margin, paper feed, form feed, text size and the receipt "
                                "content options to the standard receipt? (Printer, mode and paper width stay.)",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                                ) != QMessageBox.StandardButton.Yes:
            return
        v = self._collect()
        for k in ("receipt_columns", "receipt_left_margin", "receipt_feed_lines", "receipt_form_feed",
                  "receipt_font", "receipt_raster_font_pt"):
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
