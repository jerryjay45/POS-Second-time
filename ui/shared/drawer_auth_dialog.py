"""
ui/shared/drawer_auth_dialog.py
Small modal used to authorise a manual "open drawer with no sale".

A no-sale drawer open is a common cash-shrinkage angle in retail — it
leaves no receipt trail — so it's gated the same way void/refund
already are elsewhere in this app: a supervisor or manager password,
checked against every active supervisor/manager account (the cashier
doesn't need to know which one is on shift).

Shared across the cashier, supervisor, and manager dashboards so the
prompt looks and behaves identically everywhere it appears — including
inside the supervisor/manager windows themselves, where the logged-in
user still re-enters their password to confirm intent, matching the
same re-authorisation pattern used for void/refund in
ui/supervisor/void_refund_tab.py.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame,
)
from PyQt6.QtCore import Qt

from ui.shared.theme import (
    AMBER, AMBER_DARK, DARK, DARK_CARD, WHITE, WARM_WHITE,
    BORDER, MUTED, LABEL_TEXT, RED, RED_LIGHT, RED_BORDER,
)
from core.db_users import authenticate_supervisor_or_above


class DrawerAuthDialog(QDialog):
    """
    Prompts for a supervisor/manager password to authorise opening the
    cash drawer without a sale. On accept, self.authorized_user holds
    the authorising user's dict (id, full_name, role, ...).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.authorized_user = None
        self.setWindowTitle("Open Cash Drawer")
        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(f"background:{WHITE};")
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QFrame(); hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{DARK};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 0, 18, 0)
        t = QLabel("🔓  Open Cash Drawer")
        t.setStyleSheet(f"color:{AMBER};font-size:14px;font-weight:700;")
        x = QPushButton("✕"); x.setFixedSize(28, 28)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet("QPushButton{background:transparent;color:#888;border:none;font-size:16px;}QPushButton:hover{color:white;}")
        x.clicked.connect(self.reject)
        hl.addWidget(t); hl.addStretch(); hl.addWidget(x)
        lay.addWidget(hdr)

        body = QFrame(); body.setStyleSheet(f"background:{WHITE};")
        bl = QVBoxLayout(body); bl.setContentsMargins(18, 16, 18, 16); bl.setSpacing(10)

        msg = QLabel(
            "This opens the drawer without a sale. A supervisor or "
            "manager must authorise."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;")
        bl.addWidget(msg)

        auth_lbl = QLabel("Supervisor / Manager Password")
        auth_lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;"
                                "text-transform:uppercase;letter-spacing:0.4px;")
        bl.addWidget(auth_lbl)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter supervisor or manager password…")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setFixedHeight(42)
        self.password_input.setStyleSheet(f"""
            QLineEdit{{background:{WARM_WHITE};color:{DARK_CARD};
            border:1.5px solid {BORDER};border-radius:8px;
            padding:0 14px;font-size:14px;}}
            QLineEdit:focus{{border-color:{AMBER};background:{WHITE};}}
        """)
        self.password_input.returnPressed.connect(self._confirm)
        bl.addWidget(self.password_input)

        self.error_frame = QFrame()
        self.error_frame.setStyleSheet(f"background:{RED_LIGHT};border:1px solid {RED_BORDER};border-radius:6px;")
        ef = QHBoxLayout(self.error_frame); ef.setContentsMargins(10, 6, 10, 6)
        self.error_lbl = QLabel("")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;")
        ef.addWidget(self.error_lbl)
        self.error_frame.setVisible(False)
        bl.addWidget(self.error_frame)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        cancel = QPushButton("Cancel"); cancel.setFixedHeight(38)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton{{background:{WARM_WHITE};color:{DARK_CARD};
            border:1px solid {BORDER};border-radius:8px;font-size:13px;font-weight:600;}}
            QPushButton:hover{{background:{BORDER};}}
        """)
        cancel.clicked.connect(self.reject)
        cancel.setAutoDefault(False); cancel.setDefault(False)

        self.confirm_btn = QPushButton("🔓  Open Drawer")
        self.confirm_btn.setFixedHeight(38)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:{DARK};border:none;
            border-radius:8px;font-size:13px;font-weight:700;padding:0 20px;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        self.confirm_btn.setAutoDefault(False); self.confirm_btn.setDefault(False)
        self.confirm_btn.clicked.connect(self._confirm)

        btn_row.addWidget(cancel)
        btn_row.addWidget(self.confirm_btn, stretch=1)
        bl.addLayout(btn_row)

        lay.addWidget(body)
        self.password_input.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            return  # use the Cancel button
        super().keyPressEvent(event)

    def _confirm(self):
        password = self.password_input.text().strip()
        if not password:
            self._show_error("Please enter a supervisor or manager password.")
            return
        user = authenticate_supervisor_or_above(password)
        if not user:
            self._show_error("Incorrect password or insufficient permissions. Please try again.")
            self.password_input.clear()
            self.password_input.setFocus()
            return
        self.authorized_user = user
        self.accept()

    def _show_error(self, msg: str):
        self.error_lbl.setText(msg)
        self.error_frame.setVisible(True)
