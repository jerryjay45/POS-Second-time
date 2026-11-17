"""
ui/shared/supervisor_tools_dialog.py — the Supervisor menu on the cashier screen.

A supervisor or manager types their password once (DrawerAuthDialog); this menu then opens
with their name on it, and everything done in it is recorded under THEM, not the cashier:

    Paid-out · Safe drop · Change float · Print X-report · End of shift

It only collects input. The rules (who may do what, expected cash, locking after the
count) are in core/db_users.py and core/cash_drawer.py, the same ones the Reports tab uses,
and the database's own error is shown if a rule says no. The menu closes by itself after
90 seconds without a click, so it never stays open on an unattended till.

Not here on purpose: the cash COUNT (stays in Reports: counting from the till would show
the expected amount to whoever is counting), void/refund, no-sale open and reprint (they
already have their own buttons), and any setting.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QFrame,
)

from core import cash_drawer
from core.db_users import add_paid_out, set_session_float, get_session_by_id
from ui.shared.cash_drawer_dialogs import _spin, _btn, _label, money
from ui.shared.theme import (
    AMBER, AMBER_DARK, DARK, DARK_CARD, WHITE, WARM_WHITE, BORDER, MUTED, LABEL_TEXT, RED, GREEN,
)

IDLE_MS = 90_000


class CashEntryDialog(QDialog):
    """Amount (+ reason) for one paid-out, safe drop or float change."""

    TEXT = {
        "paid_out":  ("Paid-out",     "Cash taken from the drawer to pay for something.", True),
        "safe_drop": ("Safe drop",    "Cash moved from the drawer into the safe.",        False),
        "float":     ("Change float", "The starting cash for this shift.",                False),
    }

    def __init__(self, parent, kind: str, current_float: float | None = None):
        super().__init__(parent)
        self.kind = kind
        title, blurb, reason_required = self.TEXT[kind]
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 16, 20, 16); lay.setSpacing(8)
        lay.addWidget(_label(title, size=14, bold=True))
        lay.addWidget(_label(blurb, size=11, color=LABEL_TEXT, wrap=True))
        self.spin = _spin(current_float or 0.0)
        lay.addWidget(self.spin)
        self.reason = None
        if kind != "float":
            self.reason = QLineEdit()
            self.reason.setMaxLength(120); self.reason.setFixedHeight(34)
            self.reason.setPlaceholderText("Reason" if reason_required else "Note (optional)")
            self.reason.setStyleSheet(
                f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:7px;padding:0 10px;font-size:12px;}}QLineEdit:focus{{border-color:{AMBER};}}")
            lay.addWidget(self.reason)
        row = QHBoxLayout(); row.addStretch()
        cancel = _btn("Cancel"); cancel.clicked.connect(self.reject)
        ok = _btn("Save", primary=True); ok.clicked.connect(self.accept)
        for b in (cancel, ok):
            b.setAutoDefault(False)
        row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)
        self.spin.setFocus(); self.spin.selectAll()

    @property
    def amount(self) -> float:
        return self.spin.value()

    @property
    def reason_text(self) -> str:
        return self.reason.text() if self.reason else ""


class SupervisorToolsDialog(QDialog):
    """`end_shift_requested` is set when the supervisor picks End of shift: the cashier window
    does the closing, the count and the logout, because those need the window."""

    def __init__(self, parent, session_id: int | None, authorised_user: dict, carts_empty: bool):
        super().__init__(parent)
        self._sid = session_id
        self._auth = authorised_user
        self._carts_empty = carts_empty
        self.end_shift_requested = False
        self.setWindowTitle("Supervisor")
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(f"background:{WHITE};")
        self._idle = QTimer(self); self._idle.setSingleShot(True); self._idle.timeout.connect(self.reject)
        self._build()
        self._idle.start(IDLE_MS)

    # -- layout ------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        hdr = QFrame(); hdr.setFixedHeight(56); hdr.setStyleSheet(f"background:{DARK};")
        hl = QVBoxLayout(hdr); hl.setContentsMargins(18, 8, 18, 8); hl.setSpacing(0)
        t = QLabel("🛡  Supervisor"); t.setStyleSheet(f"color:{AMBER};font-size:14px;font-weight:700;")
        who = QLabel(f"Authorised by {self._auth.get('full_name', '?')}")
        who.setStyleSheet("color:#bbb;font-size:11px;")
        hl.addWidget(t); hl.addWidget(who)
        lay.addWidget(hdr)

        body = QFrame(); body.setStyleSheet(f"background:{WHITE};")
        bl = QVBoxLayout(body); bl.setContentsMargins(18, 14, 18, 14); bl.setSpacing(8)

        s = get_session_by_id(self._sid) if self._sid else None
        self.status = _label("", size=11, color=LABEL_TEXT, wrap=True)
        bl.addWidget(self.status)

        cash_on = cash_drawer.enabled()
        has_float = bool(s and s.get("float_amount") is not None)
        is_open = bool(s and s.get("status") == "open")
        self._buttons: dict[str, QPushButton] = {}

        def add(key, text, slot, enabled=True, tip=""):
            b = QPushButton(text); b.setFixedHeight(42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{WARM_WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:10px;font-size:13px;font-weight:600;text-align:left;padding:0 16px;}}"
                f"QPushButton:hover{{border-color:{AMBER};}}"
                f"QPushButton:disabled{{color:{MUTED};background:{WHITE};}}")
            b.setEnabled(enabled); b.setToolTip(tip)
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            bl.addWidget(b); self._buttons[key] = b

        if cash_on:
            tip = "" if has_float else "This session has no float recorded. Set the float first."
            add("paid_out",  "➖  Paid-out…",    lambda: self._cash("paid_out"),  is_open and has_float, tip)
            add("safe_drop", "🏦  Safe drop…",   lambda: self._cash("safe_drop"), is_open and has_float, tip)
            add("float",     "💵  Change float…", lambda: self._cash("float"),    is_open)
        add("x", "🧾  Print X-report", self._x_report, s is not None,
            "Totals so far for this shift. Does not close the session.")
        add("end", "⏹  End of shift…", self._end_shift, is_open and self._carts_empty,
            "" if self._carts_empty else "Complete or clear the carts first.")
        if not is_open:
            self.status.setText("No active session.")
        elif not self._carts_empty:
            self.status.setText("Carts still have items: finish or clear them before ending the shift.")
        else:
            self.status.setText(f"Session #{s['id']:05d} · opened {str(s['opened_at'])[:16]}")

        done = _btn("Done"); done.setAutoDefault(False); done.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(done)
        bl.addSpacing(4); bl.addLayout(row)
        lay.addWidget(body)

    # -- helpers -----------------------------------------------------------
    def _run(self, dlg) -> bool:
        """Run a sub-dialog with the idle timer paused, then restart it."""
        self._idle.stop()
        try:
            return bool(dlg.exec())
        finally:
            self._idle.start(IDLE_MS)

    def _note(self, text: str, ok: bool = True):
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{GREEN if ok else RED};font-size:11px;font-weight:600;border:none;")

    # -- actions -----------------------------------------------------------
    def _cash(self, kind: str):
        s = get_session_by_id(self._sid)
        dlg = CashEntryDialog(self, kind, s.get("float_amount") if kind == "float" else None)
        if not self._run(dlg):
            return
        try:
            if kind == "float":
                set_session_float(self._sid, dlg.amount, self._auth["id"])
                self._note(f"✓ Float is now {money(dlg.amount)}")
            else:
                add_paid_out(self._sid, dlg.amount, dlg.reason_text, self._auth["id"], kind)
                label = "Paid-out" if kind == "paid_out" else "Safe drop"
                self._note(f"✓ {label} of {money(dlg.amount)} recorded")
        except (ValueError, PermissionError) as e:
            self._note(str(e), ok=False)

    def _x_report(self):
        s = get_session_by_id(self._sid) if self._sid else None
        if not s:
            return
        from utils.print_manager import print_session
        self._idle.stop()
        try:
            print_session(s, "x", 1, self)
        finally:
            self._idle.start(IDLE_MS)

    def _end_shift(self):
        self._idle.stop()
        ask = QMessageBox.question(
            self, "End of shift",
            "End this shift?\n\nThe session closes and the cashier is logged out. "
            "You can count the drawer next.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if ask != QMessageBox.StandardButton.Yes:
            self._idle.start(IDLE_MS)
            return
        self.end_shift_requested = True
        self.accept()

    @property
    def authorised_user(self) -> dict:
        return self._auth
