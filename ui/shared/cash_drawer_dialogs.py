"""
ui/shared/cash_drawer_dialogs.py — the two small dialogs of the cash drawer feature.

  OpenFloatDialog   asked when a supervisor/manager opens a session by hand (the
                    "require a session" setting is on): the standard float is pre-filled.
                    Sessions that open automatically at login just take the standard float.
  CashDrawerDialog  one place for a session's cash: expected cash, change the float,
                    enter / correct the counted total, and the history of changes.

The rules (who may do what, expected cash, variance) are in core/cash_drawer.py and
core/db_users.py; this file only collects input and shows the result, and shows the
database's own error message if a rule says no.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QLineEdit, QFrame,
    QMessageBox,
)

from core.cash_drawer import session_cash_summary, standard_float
from core.db_config import get as cfg_get
from core.db_users import (
    get_session_by_id, set_session_float, set_session_count, get_cash_log,
    add_paid_out, void_paid_out, get_paid_outs, get_drawer_opens,
)
from ui.shared.checkbox import make_checkbox
from ui.shared.theme import (
    AMBER, AMBER_DARK, DARK, DARK_CARD, WARM_WHITE, WHITE, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT, RED, GREEN,
)
from utils.currency import format_currency

AMBER_TEXT = "#8a5510"          # amber that stays readable as text on light backgrounds


def money(v: float) -> str:
    """'-$2.50' (not '$-2.50') for negatives."""
    return f"-{format_currency(abs(v))}" if v < 0 else format_currency(v)


def _spin(value: float = 0.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0, 1_000_000)
    s.setDecimals(2)
    s.setSingleStep(5)
    s.setPrefix(cfg_get("currency_symbol", "$") + " ")
    s.setValue(value)
    s.setFixedHeight(34)
    s.setMinimumWidth(150)
    s.setGroupSeparatorShown(True)
    s.setStyleSheet(
        f"QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
        f"border-radius:7px;padding:0 10px;font-size:13px;font-weight:600;}}"
        f"QDoubleSpinBox:focus{{border-color:{AMBER};}}"
        f"QDoubleSpinBox:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}")
    return s


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(34)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setStyleSheet(
            f"QPushButton{{background:{AMBER};color:{DARK};border:none;border-radius:17px;"
            f"font-size:12px;font-weight:700;padding:0 16px;outline:none;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};}}"
            f"QPushButton:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}")
    else:
        b.setStyleSheet(
            f"QPushButton{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:17px;font-size:12px;font-weight:600;padding:0 16px;outline:none;}}"
            f"QPushButton:hover{{border-color:{AMBER};}}"
            f"QPushButton:disabled{{color:{MUTED};}}")
    return b


def _label(text: str, *, size=12, bold=False, color=DARK_CARD, wrap=False) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(wrap)
    l.setTextFormat(Qt.TextFormat.PlainText)
    l.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{700 if bold else 400};border:none;background:transparent;")
    return l


# ── Opening a session by hand ───────────────────────────────────────────────

class OpenFloatDialog(QDialog):
    """Pre-filled with the standard float. `float_amount` is what to open the session with."""

    def __init__(self, parent, cashier_name: str):
        super().__init__(parent)
        self.setWindowTitle("Open session")
        self.setMinimumWidth(380)
        self.setStyleSheet(f"background:{WHITE};")
        self._standard = standard_float()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(_label(f"Open a session for {cashier_name}", size=14, bold=True))
        lay.addWidget(_label("Opening float", size=11, bold=True, color=LABEL_TEXT))
        self.spin = _spin(self._standard)
        lay.addWidget(self.spin)
        self.none_cb = make_checkbox("No float for this shift", False)
        self.none_cb.toggled.connect(self._toggle_none)
        lay.addWidget(self.none_cb)
        lay.addWidget(_label(
            f"The standard float is {format_currency(self._standard)}. A different amount applies to "
            "this session only; the standard float in Setup doesn't change.", size=11, color=MUTED, wrap=True))
        row = QHBoxLayout()
        row.addStretch()
        cancel, ok = _btn("Cancel"), _btn("Open session", primary=True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _toggle_none(self, on: bool):
        self.spin.setEnabled(not on)

    @property
    def float_amount(self) -> float:
        return 0.0 if self.none_cb.isChecked() else round(self.spin.value(), 2)


# ── A session's cash ────────────────────────────────────────────────────────

class CashDrawerDialog(QDialog):
    """Expected cash, float, count and variance for one session. `changed` is True if
    anything was saved, so the caller can refresh the dashboard."""

    def __init__(self, parent, session_id: int, user: dict, focus_count: bool = False):
        super().__init__(parent)
        self._sid, self._user = session_id, user
        self._role = user.get("role", "cashier")
        self.changed = False
        self.setWindowTitle("Cash drawer")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background:{WHITE};")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(20, 16, 20, 16)
        self._root.setSpacing(8)
        self._build()
        if focus_count and self.count_spin.isEnabled():
            self.count_spin.setFocus()
            self.count_spin.selectAll()

    # -- layout ------------------------------------------------------------
    def _build(self):
        r = self._root
        self.title = _label("", size=14, bold=True)
        self.subtitle = _label("", size=11, color=LABEL_TEXT)
        r.addWidget(self.title)
        r.addWidget(self.subtitle)

        self.rows_box = QFrame()
        self.rows_box.setStyleSheet(f"QFrame{{background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;}}")
        self.rows = QVBoxLayout(self.rows_box)
        self.rows.setContentsMargins(12, 8, 12, 8)
        self.rows.setSpacing(4)
        r.addWidget(self.rows_box)

        self.variance_lbl = _label("", size=14, bold=True)
        self.variance_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r.addWidget(self.variance_lbl)

        # float
        self.float_head = _label("Change the float", size=11, bold=True, color=LABEL_TEXT)
        r.addWidget(self.float_head)
        fr = QHBoxLayout()
        self.float_spin = _spin()
        self.float_btn = _btn("Update float")
        self.float_btn.clicked.connect(self._save_float)
        fr.addWidget(self.float_spin); fr.addWidget(self.float_btn); fr.addStretch()
        self.float_row = fr
        r.addLayout(fr)

        # count
        self.count_head = _label("Counted cash", size=11, bold=True, color=LABEL_TEXT)
        r.addWidget(self.count_head)
        cr = QHBoxLayout()
        self.count_spin = _spin()
        self.count_btn = _btn("Save count", primary=True)
        self.count_btn.clicked.connect(self._save_count)
        cr.addWidget(self.count_spin); cr.addWidget(self.count_btn); cr.addStretch()
        r.addLayout(cr)
        self.count_note = _label("", size=11, color=MUTED, wrap=True)
        r.addWidget(self.count_note)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Note (optional), kept with the change")
        self.note_edit.setMaxLength(120)
        self.note_edit.setFixedHeight(30)
        self.note_edit.setStyleSheet(
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;"
            f"padding:0 10px;font-size:12px;}}QLineEdit:focus{{border-color:{AMBER};}}")
        r.addWidget(self.note_edit)

        # paid-outs
        self.po_head = _label("Paid out / safe drop", size=11, bold=True, color=LABEL_TEXT)
        r.addWidget(self.po_head)
        self.po_form = QFrame(); self.po_form.setStyleSheet("QFrame{border:none;background:transparent;}")
        pr = QHBoxLayout(self.po_form); pr.setContentsMargins(0, 0, 0, 0)
        self.po_spin = _spin()
        self.po_reason = QLineEdit(); self.po_reason.setPlaceholderText("Reason (needed for a paid-out)")
        self.po_reason.setMaxLength(120); self.po_reason.setFixedHeight(34)
        self.po_reason.setStyleSheet(
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};border-radius:7px;"
            f"padding:0 10px;font-size:12px;}}QLineEdit:focus{{border-color:{AMBER};}}")
        self.po_btn = _btn("Paid-out"); self.po_btn.clicked.connect(lambda: self._save_paid_out("paid_out"))
        self.sd_btn = _btn("Safe drop"); self.sd_btn.clicked.connect(lambda: self._save_paid_out("safe_drop"))
        pr.addWidget(self.po_spin); pr.addWidget(self.po_reason, stretch=1)
        pr.addWidget(self.po_btn); pr.addWidget(self.sd_btn)
        r.addWidget(self.po_form)
        self.po_box = QVBoxLayout(); self.po_box.setSpacing(2)
        r.addLayout(self.po_box)
        self.opens_lbl = _label("", size=11, color=LABEL_TEXT, wrap=True)
        r.addWidget(self.opens_lbl)

        self.log_head = _label("Changes", size=11, bold=True, color=LABEL_TEXT)
        self.log_box = QVBoxLayout()
        self.log_box.setSpacing(2)
        r.addWidget(self.log_head)
        r.addLayout(self.log_box)

        close = _btn("Close")
        close.clicked.connect(self.accept)
        br = QHBoxLayout(); br.addStretch(); br.addWidget(close)
        r.addLayout(br)
        self._refresh()

    # -- state -------------------------------------------------------------
    def _clear(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide(); w.setParent(None); w.deleteLater()

    def _row(self, label: str, value: str, bold=False, color=DARK_CARD):
        h = QHBoxLayout()
        h.addWidget(_label(label, bold=bold))
        h.addStretch()
        h.addWidget(_label(value, bold=bold, color=color))
        host = QFrame()
        host.setStyleSheet("QFrame{border:none;background:transparent;}")
        host.setLayout(h)
        h.setContentsMargins(0, 0, 0, 0)
        self.rows.addWidget(host)

    def _refresh(self):
        s = get_session_by_id(self._sid)
        if not s:
            self.reject()
            return
        summary = session_cash_summary(s)
        is_open = s["status"] == "open"
        counted = s.get("counted_cash")
        self.title.setText(f"Cash drawer · Session #{s['id']:05d}")
        self.subtitle.setText(("Active" if is_open else "Closed") + f" · opened {str(s['opened_at'])[:16]}"
                              + ("" if is_open else f" · closed {str(s['closed_at'])[:16]}"))

        self._clear(self.rows)
        if summary is None:
            self._row("No float was recorded for this session", "", color=MUTED)
            self.variance_lbl.setText("")
        else:
            self._row("Opening float", money(summary["float"]))
            self._row("Cash sales", money(summary["cash_sales"]))
            self._row("Cash refunds", money(-summary["cash_refunds"]) if summary["cash_refunds"] else money(0),
                      color=RED if summary["cash_refunds"] else DARK_CARD)
            if summary["paid_outs"]:
                self._row("Paid out", money(-summary["paid_outs"]), color=RED)
            if summary["safe_drops"]:
                self._row("Safe drops", money(-summary["safe_drops"]), color=RED)
            self._row("Expected cash" + (" so far" if is_open else ""), money(summary["expected"]), bold=True)
            if summary["counted"] is not None:
                self._row("Counted cash", money(summary["counted"]), bold=True)
            v = summary["variance"]
            if v is None:
                self.variance_lbl.setText("Count pending" if summary["pending"] else "")
                self.variance_lbl.setStyleSheet(f"color:{AMBER_TEXT};font-size:14px;font-weight:700;border:none;")
            elif v == 0:
                self.variance_lbl.setText("Balanced")
                self.variance_lbl.setStyleSheet(f"color:{GREEN};font-size:14px;font-weight:700;border:none;")
            else:
                self.variance_lbl.setText(f"{'Over' if v > 0 else 'Short'} by {format_currency(abs(v))}")
                self.variance_lbl.setStyleSheet(
                    f"color:{AMBER_TEXT if v > 0 else RED};font-size:14px;font-weight:700;border:none;")

        # float: editable while open, or after closing until the count is entered
        can_float = self._role in ("supervisor", "manager") and (is_open or counted is None)
        self.float_head.setText("Change the float" if summary else "Set the float")
        self.float_head.setVisible(can_float)
        self.float_spin.setVisible(can_float); self.float_btn.setVisible(can_float)
        if can_float:
            self.float_spin.setValue(summary["float"] if summary else 0.0)

        # count: closed sessions with a float; first count supervisor+manager, correction manager only
        can_count = (not is_open and summary is not None and self._role in ("supervisor", "manager")
                     and (counted is None or self._role == "manager"))
        self.count_spin.setEnabled(can_count)
        self.count_btn.setEnabled(can_count)
        self.count_btn.setText("Correct count" if counted is not None else "Save count")
        if counted is not None:
            self.count_spin.setValue(counted)
        if summary is None:
            note = "There is no expected cash to count against."
        elif is_open:
            note = "Close the session first, then count the drawer and enter the total here."
        elif counted is not None and self._role != "manager":
            note = "Only a manager can correct a saved count."
        elif counted is not None:
            note = (f"Counted by {summary['counted_by'] or 'unknown'} · {str(summary['counted_at'])[:16]}. "
                    "A correction keeps the old value in the list below.")
        else:
            note = "Count the drawer and enter the total now, or come back later: it stays pending."
        self.count_note.setText(note)
        # Counting switched off (Setup -> Cash Drawer) and this session was never counted:
        # no count box at all. A count that already exists stays visible, and a manager can still fix it.
        show_count = not (summary is not None and not summary["count_on"] and counted is None)
        for w in (self.count_head, self.count_spin, self.count_btn, self.count_note):
            w.setVisible(show_count)

        # paid-outs: record while open, or after closing until counted (like the float)
        can_po = (self._role in ("supervisor", "manager") and summary is not None
                  and (is_open or counted is None))
        self.po_form.setVisible(can_po)
        paid = get_paid_outs(self._sid, include_voided=True) if summary is not None else []
        self.po_head.setVisible(can_po or bool(paid))
        self._clear(self.po_box)
        for p in paid[:8]:
            voided = bool(p["voided_at"])
            row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
            what = "Safe drop" if p["kind"] == "safe_drop" else "Paid out"
            line = (f"{str(p['recorded_at'])[5:16]} · {what} {money(p['amount'])} · {p['reason']}"
                    f" · {p['recorded_by_name'] or '?'}")
            if voided:
                line += f" · VOIDED by {p['voided_by_name'] or '?'}"
            lab = _label(line, size=11, color=MUTED if voided else LABEL_TEXT, wrap=True)
            if voided:
                lab.setStyleSheet(lab.styleSheet() + "text-decoration:line-through;")
            row.addWidget(lab, stretch=1)
            if not voided and self._role == "manager":
                vb = _btn("Void"); vb.setFixedHeight(24)
                vb.clicked.connect(lambda _=False, pid=p["id"]: self._void_paid_out(pid))
                row.addWidget(vb)
            host = QFrame(); host.setStyleSheet("QFrame{border:none;background:transparent;}")
            host.setLayout(row); self.po_box.addWidget(host)

        opens = get_drawer_opens(self._sid, limit=3)
        n_opens = summary["no_sale_opens"] if summary else 0
        self.opens_lbl.setVisible(bool(n_opens))
        if n_opens:
            last = opens[0]
            self.opens_lbl.setText(f"No-sale drawer opens this session: {n_opens} · latest "
                                   f"{str(last['opened_at'])[11:16]}, authorised by {last['authorised_by_name'] or '?'}")

        self._clear(self.log_box)
        log = get_cash_log(self._sid, limit=6)
        self.log_head.setVisible(bool(log))
        for e in log:
            what = "Float" if e["kind"] == "float" else "Count"
            was = "" if e["old_value"] is None else f"{money(e['old_value'])} → "
            line = f"{str(e['changed_at'])[5:16]} · {what} {was}{money(e['new_value'])} · {e['changed_by_name'] or '?'}"
            if e.get("note"):
                line += f" · {e['note']}"
            self.log_box.addWidget(_label(line, size=11, color=LABEL_TEXT, wrap=True))
        self.adjustSize()

    # -- saving ------------------------------------------------------------
    def _save(self, fn, value):
        try:
            fn(self._sid, value, self._user["id"], self.note_edit.text())
        except (ValueError, PermissionError) as e:
            QMessageBox.warning(self, "Cash drawer", str(e))
            self._refresh()
            return
        self.changed = True
        self.note_edit.clear()
        self._refresh()

    def _save_float(self):
        self._save(set_session_float, self.float_spin.value())

    def _save_count(self):
        self._save(set_session_count, self.count_spin.value())

    def _save_paid_out(self, kind: str = "paid_out"):
        try:
            add_paid_out(self._sid, self.po_spin.value(), self.po_reason.text(), self._user["id"], kind)
        except (ValueError, PermissionError) as e:
            QMessageBox.warning(self, "Cash drawer", str(e))
            return
        self.changed = True
        self.po_spin.setValue(0); self.po_reason.clear()
        self._refresh()

    def _void_paid_out(self, paid_out_id: int):
        if QMessageBox.question(self, "Void entry", "Void this entry? Expected cash goes back up by "
                                "that amount, and the entry stays in the list as voided.") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            void_paid_out(paid_out_id, self._user["id"])
        except (ValueError, PermissionError) as e:
            QMessageBox.warning(self, "Cash drawer", str(e))
            return
        self.changed = True
        self._refresh()
