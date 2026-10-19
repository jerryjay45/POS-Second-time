"""
Printer calibration. A raw / parallel-to-USB printer cannot tell the program how
wide its paper is or how far the print head sits from the tear bar, so this
dialog prints two test sheets and asks the person two simple questions:

  1. Width — "What is the last column number you can read on the first ruler line?"
  2. Feed  — "After tearing the paper off, what is the last full numbered line on
             the piece you tore off?"

The answers become the "columns" and "feed lines" settings. The sheets ignore the
saved margin and feed on purpose, so they measure the raw printer.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QFrame, QLayout)

from ui.shared.theme import (AMBER, AMBER_DARK, DARK, DARK_CARD, WARM_WHITE, WHITE,
                             BORDER, MUTED, GREEN)
from utils import calibration_sheet as CS


class CalibrationDialog(QDialog):
    def __init__(self, parent, current_columns: int, has_cutter: bool, printer_mode: str):
        super().__init__(parent)
        self.setWindowTitle("Calibrate printer")
        self.setMinimumWidth(620)
        self.setStyleSheet(f"QDialog{{background:{WHITE};}}")
        self._cols_touched = False
        self._has_cutter = has_cutter

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel("Calibrate printer")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:17px;font-weight:700;")
        lay.addWidget(title)
        intro = QLabel(
            "Windows can't tell the program how wide the paper is or how far to feed it, "
            "so we measure it. Each test prints a short sheet. The sheets use your saved "
            "printer settings (mode, ESC/POS, font, cutter) but ignore the saved margin and feed. Calibrate again after changing the font.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{MUTED};font-size:12px;")
        lay.addWidget(intro)
        if printer_mode == "raster":
            warn = QLabel("Raster mode prints graphics, so column and feed measurements from these "
                          "text sheets don't apply. Switch to Raw mode to calibrate.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#8A4B00;background:#FFF3CD;border:1px solid #E0A800;"
                               "border-radius:6px;padding:6px 8px;font-size:12px;font-weight:600;")
            lay.addWidget(warn)

        # ── 1. width ────────────────────────────────────────────────
        lay.addWidget(self._box(
            "1.  Paper width",
            "Print the width test. Look at the FIRST ruler line (the printer may wrap the rest "
            "onto another line) and enter the last number you can read.",
            "Print width test", lambda: self._print(CS.ruler_lines()),
            self._cols_row(current_columns)))

        # ── 2. feed ─────────────────────────────────────────────────
        self.feed_result = QLabel("")
        self.feed_result.setStyleSheet(f"color:{MUTED};font-size:12px;")
        lay.addWidget(self._box(
            "2.  Paper feed after printing",
            ("Print the feed test. When it stops, tear the paper off at the tear bar and enter the "
             "last FULL numbered line on the piece you tore off (1 to %d). If you can read every "
             "line, enter %d." % (CS.FEED_TEST_LINES, CS.FEED_TEST_LINES))
            + ("\nYour printer has an automatic cutter, which feeds and cuts by itself, so this "
               "step is usually unnecessary." if has_cutter else ""),
            "Print feed test", lambda: self._print(CS.feed_test_lines()),
            self._feed_row()))

        # ── 3. style ────────────────────────────────────────────────
        lay.addWidget(self._box(
            "3.  Look at the text styles (optional)",
            "Prints bold text and a few special characters, so you can see what "
            "your printer can do.",
            "Print style test", lambda: self._print(CS.style_test_lines()), None))

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        cancel.setStyleSheet(f"QPushButton{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                             f"border-radius:7px;padding:8px 18px;font-size:13px;}}")
        use = QPushButton("Use these results")
        use.setDefault(True)
        use.clicked.connect(self.accept)
        use.setStyleSheet(f"QPushButton{{background:{AMBER};color:{DARK};border:none;border-radius:7px;"
                          f"padding:8px 18px;font-size:13px;font-weight:700;}}"
                          f"QPushButton:hover{{background:{AMBER_DARK};}}")
        row.addWidget(cancel)
        row.addWidget(use)
        lay.addLayout(row)
        self._update_feed_hint()

    def _fit_height(self):
        """Word-wrapped labels report too small a height unless the layout is asked
        for the height needed at the dialog's actual width — without this the
        instructions were clipped and the Print buttons squashed."""
        w = max(self.width(), self.minimumWidth())
        h = self.layout().totalHeightForWidth(w)
        if h > 0:
            self.setMinimumHeight(h)
            if self.height() < h:
                self.resize(w, h)

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_height()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_height()

    # ── pieces ──────────────────────────────────────────────────────────
    def _box(self, heading, text, button_text, on_click, extra_row):
        box = QFrame()
        box.setStyleSheet(f"QFrame{{background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;}}")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 12)
        bl.setSpacing(8)
        h = QLabel(heading)
        h.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;border:none;")
        t = QLabel(text)
        t.setWordWrap(True)
        t.setStyleSheet(f"color:{MUTED};font-size:12px;border:none;")
        bl.addWidget(h)
        bl.addWidget(t)
        btn = QPushButton(button_text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(on_click)
        btn.setStyleSheet(f"QPushButton{{background:{WHITE};color:{DARK_CARD};border:1.5px solid {AMBER};"
                          f"border-radius:7px;padding:7px 14px;font-size:12px;font-weight:600;}}"
                          f"QPushButton:hover{{background:{AMBER};color:{DARK};}}")
        r = QHBoxLayout()
        r.addWidget(btn)
        r.addStretch()
        bl.addLayout(r)
        if extra_row is not None:
            bl.addLayout(extra_row)
        return box

    def _cols_row(self, current_columns):
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(16, 80)
        self.cols_spin.setValue(max(16, min(80, int(current_columns))))
        self.cols_spin.setFixedWidth(80)
        self.cols_spin.valueChanged.connect(lambda _v: setattr(self, "_cols_touched", True))
        r = QHBoxLayout()
        lbl = QLabel("Last column number visible:")
        lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;border:none;")
        r.addWidget(lbl)
        r.addWidget(self.cols_spin)
        r.addStretch()
        return r

    def _feed_row(self):
        self.last_line_spin = QSpinBox()
        self.last_line_spin.setRange(0, CS.FEED_TEST_LINES)
        self.last_line_spin.setSpecialValueText("not entered")
        self.last_line_spin.setFixedWidth(110)
        self.last_line_spin.valueChanged.connect(lambda _v: self._update_feed_hint())
        r = QHBoxLayout()
        lbl = QLabel("Last full line on the torn piece:")
        lbl.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:600;border:none;")
        r.addWidget(lbl)
        r.addWidget(self.last_line_spin)
        r.addWidget(self.feed_result)
        r.addStretch()
        return r

    # ── behaviour ───────────────────────────────────────────────────────
    def _print(self, lines):
        from utils.print_manager import print_lines
        print_lines(lines, self, finish=False)

    def _update_feed_hint(self):
        n = self.last_line_spin.value()
        if n == 0:
            self.feed_result.setText("")
            return
        feed = CS.suggest_feed(CS.FEED_TEST_LINES, n)
        self.feed_result.setText(f"→ feed {feed} blank line{'s' if feed != 1 else ''}")
        self.feed_result.setStyleSheet(f"color:{GREEN};font-size:12px;font-weight:700;border:none;")

    def results(self) -> dict[str, str]:
        """Only the answers the person actually gave."""
        out: dict[str, str] = {}
        if self._cols_touched:
            out["receipt_columns"] = str(self.cols_spin.value())
        if self.last_line_spin.value() > 0:
            out["receipt_feed_lines"] = str(CS.suggest_feed(CS.FEED_TEST_LINES,
                                                            self.last_line_spin.value()))
        return out
