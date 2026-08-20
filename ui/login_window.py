"""
ui/login_window.py
Login screen — authenticates user and routes to the correct dashboard.

Design: warm white card, amber hex logo, Inter font, show/hide password,
        Enter key submits, inline error message, zoom controls.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSizePolicy,
    QSpacerItem, QGraphicsDropShadowEffect,
)
from PyQt6.QtCore  import Qt, QSize, pyqtSignal
from PyQt6.QtGui   import (
    QFont, QColor, QPainter, QPolygonF, QPainterPath,
    QBrush, QPen, QKeyEvent,
)
import math

from ui.shared.theme import (
    AMBER, AMBER_DARK, DARK_CARD, WARM_WHITE, WHITE,
    BORDER, MUTED, RED, RED_LIGHT, RED_BORDER, LABEL_TEXT,
    MAIN_FONT,
)
from core.db_users  import authenticate, get_open_session
from core.db_config import get_business, get_int, set as cfg_set, get_bool


# ── Hex logo widget ───────────────────────────────────────────────────────────

class HexLogo(QWidget):
    """Draws a filled hexagon in amber."""
    def __init__(self, size: int = 44, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self._size / 2, self._size / 2, self._size / 2 - 2
        path = QPainterPath()
        for i in range(6):
            angle = math.radians(60 * i - 30)
            x, y = cx + r * math.cos(angle), cy + r * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        painter.fillPath(path, QBrush(QColor(AMBER)))


# ── Zoom button ───────────────────────────────────────────────────────────────

class ZoomBtn(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(26, 26)
        self.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid {BORDER};
                border-radius: 5px;
                background: {WHITE};
                color: {DARK_CARD};
                font-size: 14px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: {AMBER};
                color: {AMBER};
            }}
        """)


# ── Password field with show/hide toggle ─────────────────────────────────────

class PasswordField(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setPlaceholderText("Enter your password")
        self.textChanged.connect(
            lambda t: self.setText(t.upper()) if t != t.upper() else None
        )

        self._btn = QPushButton("👁", self)
        self._btn.setFixedSize(28, 28)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet("""
            QPushButton {
                border: none; background: transparent;
                font-size: 14px; color: #B4B2A9;
            }
            QPushButton:hover { color: #5F5E5A; }
        """)
        self._btn.clicked.connect(self._toggle)
        self._visible = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._btn.move(self.width() - 34, (self.height() - 28) // 2)

    def _toggle(self):
        self._visible = not self._visible
        self.setEchoMode(
            QLineEdit.EchoMode.Normal if self._visible
            else QLineEdit.EchoMode.Password
        )
        self._btn.setText("🙈" if self._visible else "👁")


# ── Login card ────────────────────────────────────────────────────────────────

class LoginCard(QFrame):
    login_success = pyqtSignal(dict)   # emits user dict on success

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("loginCard")
        self.setFixedWidth(360)
        self.setStyleSheet(f"""
            QFrame#loginCard {{
                background-color: {WHITE};
                border: 1px solid {BORDER};
                border-radius: 16px;
            }}
        """)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 30))
        self.setGraphicsEffect(shadow)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(0)

        # ── Logo + title ──────────────────────────────────────────────────────
        logo_row = QHBoxLayout()
        logo_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_row.addWidget(HexLogo(44))
        layout.addLayout(logo_row)
        layout.addSpacing(16)

        biz = get_business()
        title = QLabel(biz.get("name", "Merchant POS Systems"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 20px; font-weight: 700;
            color: {DARK_CARD}; letter-spacing: -0.4px;
        """)
        layout.addWidget(title)
        layout.addSpacing(4)

        sub = QLabel("Sign in to continue")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"font-size: 13px; color: {LABEL_TEXT};")
        layout.addWidget(sub)
        layout.addSpacing(24)

        # ── Username ──────────────────────────────────────────────────────────
        layout.addWidget(self._field_label("Username"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your username")
        self.username_input.setFixedHeight(40)
        self.username_input.setStyleSheet(self._input_style())
        self.username_input.returnPressed.connect(self._attempt_login)
        self.username_input.textChanged.connect(
            lambda t: self.username_input.setText(t.upper()) if t != t.upper() else None
        )
        layout.addWidget(self.username_input)
        layout.addSpacing(12)

        # ── Password ──────────────────────────────────────────────────────────
        layout.addWidget(self._field_label("Password"))
        self.password_input = PasswordField()
        self.password_input.setFixedHeight(40)
        self.password_input.setStyleSheet(self._input_style())
        self.password_input.returnPressed.connect(self._attempt_login)
        layout.addWidget(self.password_input)
        layout.addSpacing(4)

        # ── Error message (hidden by default) ─────────────────────────────────
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.error_label.setStyleSheet(f"""
            background: {RED_LIGHT};
            border: 1px solid {RED_BORDER};
            border-radius: 6px;
            color: {RED};
            font-size: 12px;
            padding: 7px 10px;
        """)
        layout.addSpacing(6)
        layout.addWidget(self.error_label)

        # ── Sign in button ────────────────────────────────────────────────────
        layout.addSpacing(16)
        self.sign_btn = QPushButton("Sign In")
        self.sign_btn.setFixedHeight(42)
        self.sign_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sign_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {AMBER};
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: 0.1px;
            }}
            QPushButton:hover   {{ background-color: {AMBER_DARK}; }}
            QPushButton:pressed {{ background-color: #633806; }}
            QPushButton:disabled {{ background-color: #D3D1C7; }}
        """)
        self.sign_btn.clicked.connect(self._attempt_login)
        layout.addWidget(self.sign_btn)

        # ── Footer: version + zoom ────────────────────────────────────────────
        layout.addSpacing(20)
        footer = QHBoxLayout()
        self._zoom = get_int("ui_scale_pct", 100)

        ver = QLabel("v1.0.0")
        ver.setStyleSheet(f"font-size: 11px; color: {MUTED}; font-family: 'DM Mono', monospace;")
        footer.addWidget(ver)
        footer.addStretch()

        self._zoom_label = QLabel(f"{self._zoom}%")
        self._zoom_label.setStyleSheet(
            f"font-size: 11px; color: {DARK_CARD}; min-width: 36px; text-align: center;"
        )
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        z_minus = ZoomBtn("−")
        z_plus  = ZoomBtn("+")
        z_minus.clicked.connect(lambda: self._change_zoom(-10))
        z_plus.clicked.connect(lambda:  self._change_zoom(+10))

        footer.addWidget(z_minus)
        footer.addWidget(self._zoom_label)
        footer.addWidget(z_plus)
        layout.addLayout(footer)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {LABEL_TEXT};"
            "text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 5px;"
        )
        return lbl

    def _input_style(self) -> str:
        return f"""
            QLineEdit {{
                background: #FAFAF8;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 0 12px;
                font-size: 13px;
                color: {DARK_CARD};
            }}
            QLineEdit:focus {{ border-color: {AMBER}; background: {WHITE}; }}
        """

    def _show_error(self, msg: str):
        self.error_label.setText(msg)
        self.error_label.setVisible(True)

    def _clear_error(self):
        self.error_label.setVisible(False)
        self.error_label.setText("")

    def _change_zoom(self, delta: int):
        self._zoom = max(70, min(150, self._zoom + delta))
        self._zoom_label.setText(f"{self._zoom}%")
        cfg_set("ui_scale_pct", str(self._zoom))
        # Propagate to main window
        if self.window():
            self.window().apply_zoom(self._zoom)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _attempt_login(self):
        self._clear_error()
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username:
            self._show_error("Please enter your username.")
            self.username_input.setFocus()
            return
        if not password:
            self._show_error("Please enter your password.")
            self.password_input.setFocus()
            return

        self.sign_btn.setEnabled(False)
        self.sign_btn.setText("Signing in…")

        user = authenticate(username, password)

        self.sign_btn.setEnabled(True)
        self.sign_btn.setText("Sign In")

        if user is None:
            self._show_error("Invalid username or password.")
            self.password_input.clear()
            self.username_input.setFocus()
            return

        # Clear fields before emitting
        self.username_input.clear()
        self.password_input.clear()
        self.login_success.emit(user)


# ── Login Window ──────────────────────────────────────────────────────────────

class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Merchant POS Systems")
        self.setMinimumSize(480, 520)
        self._build_ui()
        self._center_on_screen()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet(f"background-color: {WARM_WHITE};")

        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = LoginCard()
        self.card.login_success.connect(self._on_login)
        layout.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignCenter)

    def _center_on_screen(self):
        from PyQt6.QtGui import QScreen
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width()  // 2,
                geo.center().y() - self.height() // 2,
            )

    def apply_zoom(self, pct: int):
        """Scale the window font size based on zoom percentage."""
        factor = pct / 100.0
        font = self.font()
        font.setPointSizeF(10 * factor)
        self.setFont(font)

    # ── Routing ───────────────────────────────────────────────────────────────

    def _on_login(self, user: dict):
        role = user.get("role", "cashier")

        if role == "cashier":
            # Check session gate
            if get_bool("session_gate", False) and not get_open_session(user["id"]):
                self.card._show_error(
                    "No active session. Ask your supervisor to open one before you log in."
                )
                return
            from ui.cashier.cashier_window import CashierWindow
            self._next = CashierWindow(user)
        elif role == "supervisor":
            from ui.supervisor.supervisor_window import SupervisorWindow
            self._next = SupervisorWindow(user)
        elif role == "manager":
            from ui.manager.manager_window import ManagerWindow
            self._next = ManagerWindow(user)
        else:
            self.card._show_error(f"Unknown role: {role}")
            return

        self._next.showMaximized()
        self.hide()

        # Re-show login when the next window is closed
        self._next.destroyed.connect(self.show)
        self._next.logout_requested.connect(self._handle_logout)

    def _handle_logout(self):
        """Called when any dashboard emits logout_requested."""
        self.show()
