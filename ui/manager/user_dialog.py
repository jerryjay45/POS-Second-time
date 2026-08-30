"""
ui/manager/user_dialog.py
Add / edit user — modal dialog.

Replaces the old always-visible right-panel form in the Users tab with a
pop-up, styled to match the other dialogs in the app (see
ui/cashier/misc_dialog.py for the reference pattern: dark header with a
title + close icon, a white body with labeled fields, and a footer button
row).

Usage:
    dlg = UserDialog(parent, current_user_id=self.user["id"])            # add
    dlg = UserDialog(parent, current_user_id=self.user["id"], editing=u) # edit
    if dlg.exec() == QDialog.DialogCode.Accepted:
        self._usr_load()   # user list changed — refresh
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFrame, QWidget, QMessageBox,
)
from PyQt6.QtCore import Qt, QSize, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QIcon, QPixmap, QPolygonF

from ui.shared.theme import (
    AMBER, AMBER_DARK,
    DARK, DARK_CARD, WHITE, WARM_WHITE,
    BORDER, MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN,
)
from core.db_users import add_user, update_user, delete_user


class UserDialog(QDialog):
    """Add or edit a single user. On accept, the user list has already
    been written to the DB — the caller just needs to refresh its table."""

    def __init__(self, parent=None, current_user_id=None, editing: dict | None = None):
        super().__init__(parent)
        self._current_user_id = current_user_id
        self._editing_id = editing["id"] if editing else None
        self.setModal(True)
        self.setFixedWidth(380)
        self.setStyleSheet(f"background:{WHITE};")
        self._build_ui()
        if editing:
            self._prefill(editing)

    # ================================================================
    # UI
    # ================================================================

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QFrame(); hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{DARK};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 0, 18, 0)
        self.title_lbl = QLabel("Add User")
        self.title_lbl.setStyleSheet("color:white;font-size:14px;font-weight:700;")
        x = QPushButton(); x.setFixedSize(28, 28)
        x.setIcon(self._draw_x_icon("white")); x.setIconSize(QSize(14, 14))
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            "QPushButton{background:transparent;border:none;}"
            "QPushButton:hover{background:rgba(255,255,255,0.12);border-radius:14px;}"
        )
        x.clicked.connect(self.reject)
        hl.addWidget(self.title_lbl); hl.addStretch(); hl.addWidget(x)
        lay.addWidget(hdr)

        # Body
        body = QWidget(); body.setStyleSheet(f"background:{WHITE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 18, 20, 18)
        bl.setSpacing(14)

        bl.addWidget(self._lbl("Full Name"))
        self.f_fullname = self._upper_input("e.g. Jane Smith")
        bl.addWidget(self.f_fullname)

        bl.addWidget(self._lbl("Username"))
        self.f_username = self._upper_input("Login username")
        bl.addWidget(self.f_username)

        bl.addWidget(self._lbl("Password"))
        self.f_password = QLineEdit()
        self.f_password.setFixedHeight(40)
        self.f_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_password.setPlaceholderText("Password (leave blank to keep)")
        self.f_password.setStyleSheet(self._inp())
        self.f_password.textChanged.connect(
            lambda t: self.f_password.setText(t.upper()) if t != t.upper() else None
        )
        bl.addWidget(self.f_password)

        role_row = QHBoxLayout(); role_row.setSpacing(12)
        role_col = QVBoxLayout(); role_col.setSpacing(6)
        role_col.addWidget(self._lbl("Role"))
        self.f_role = QComboBox(); self.f_role.setFixedHeight(40)
        self.f_role.addItems(["cashier", "supervisor", "manager"])
        self.f_role.setStyleSheet(self._combo())
        role_col.addWidget(self.f_role)
        role_row.addLayout(role_col, stretch=1)
        bl.addLayout(role_row)

        self.f_active = QCheckBox("Active")
        self.f_active.setChecked(True)
        self.f_active.setStyleSheet(f"""
            QCheckBox{{color:{DARK_CARD};font-size:13px;font-weight:500;}}
            QCheckBox::indicator{{width:18px;height:18px;
            border:1.5px solid {BORDER};border-radius:4px;background:{WHITE};}}
            QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}
        """)
        bl.addWidget(self.f_active)

        # Feedback / error label
        self.feedback_lbl = QLabel("")
        self.feedback_lbl.setWordWrap(True)
        self.feedback_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feedback_lbl.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;min-height:16px;background:transparent;")
        bl.addWidget(self.feedback_lbl)

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setFixedHeight(40)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setStyleSheet(f"""
            QPushButton{{background:{RED_LIGHT};color:{RED};border:none;
            border-radius:20px;font-size:13px;font-weight:600;padding:0 16px;}}
            QPushButton:hover{{background:{RED};color:white;}}
        """)
        self.delete_btn.clicked.connect(self._delete)
        self.delete_btn.setVisible(False)

        cancel = QPushButton("Cancel"); cancel.setFixedHeight(40)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton{{background:{DARK_CARD};color:white;border:none;
            border-radius:20px;font-size:13px;font-weight:600;padding:0 20px;}}
            QPushButton:hover{{background:#444;}}
        """)
        cancel.clicked.connect(self.reject)

        self.save_btn = QPushButton("💾  Save")
        self.save_btn.setFixedHeight(40)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(f"""
            QPushButton{{background:{AMBER};color:{DARK};border:none;
            border-radius:20px;font-size:13px;font-weight:700;padding:0 20px;}}
            QPushButton:hover{{background:{AMBER_DARK};}}
        """)
        self.save_btn.clicked.connect(self._save)

        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(self.save_btn)
        bl.addLayout(btn_row)

        lay.addWidget(body)
        self.f_fullname.setFocus()

    # ================================================================
    # DATA
    # ================================================================

    def _prefill(self, u: dict):
        self.title_lbl.setText(f"Edit: {u['full_name']}")
        self.f_fullname.setText(u["full_name"])
        self.f_username.setText(u["username"])
        idx = self.f_role.findText(u["role"])
        if idx >= 0:
            self.f_role.setCurrentIndex(idx)
        self.f_active.setChecked(bool(u["is_active"]))
        # Can't delete the account you're currently logged in as
        self.delete_btn.setVisible(u["id"] != self._current_user_id)

    def _save(self):
        full_name = self.f_fullname.text().strip()
        username  = self.f_username.text().strip()
        password  = self.f_password.text()
        role      = self.f_role.currentText()
        is_active = self.f_active.isChecked()
        if not full_name or not username:
            self._err("Full name and username are required."); return
        if self._editing_id is None and not password:
            self._err("Password required for new user."); return
        try:
            if self._editing_id is None:
                add_user(full_name, username, password, role, is_active)
            else:
                update_user(self._editing_id, full_name=full_name, username=username,
                            password=password or None, role=role, is_active=is_active)
            self.accept()
        except Exception as e:
            self._err(str(e))

    def _delete(self):
        if not self._editing_id or self._editing_id == self._current_user_id:
            return
        reply = QMessageBox.question(
            self, "Delete User",
            f"Delete '{self.f_fullname.text().strip()}'?\n\nTransaction history will not be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_user(self._editing_id)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", str(e))

    def _err(self, msg):
        self.feedback_lbl.setStyleSheet(f"color:{RED};font-size:11px;font-weight:600;min-height:16px;background:transparent;")
        self.feedback_lbl.setText(msg)

    # ================================================================
    # STYLE HELPERS
    # ================================================================

    def _upper_input(self, placeholder: str) -> QLineEdit:
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(40)
        inp.setStyleSheet(self._inp())
        inp.textChanged.connect(
            lambda t, w=inp: w.setText(t.upper()) if t != t.upper() else None
        )
        return inp

    def _inp(self) -> str:
        return (
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:8px;"
            f"padding:0 12px;font-size:14px;font-weight:500;}}"
            f"QLineEdit:focus{{border-color:{AMBER};}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
        )

    def _combo(self) -> str:
        return (
            f"QComboBox{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:8px;"
            f"padding:0 12px;font-size:14px;font-weight:500;}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:24px;}}"
        )

    def _lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{LABEL_TEXT};font-size:11px;font-weight:600;"
            "text-transform:uppercase;letter-spacing:0.4px;"
        )
        return l

    def _draw_x_icon(self, color: str, size: int = 18) -> QIcon:
        """Hand-painted close icon — no text glyph / font dependency.
        (See ui/supervisor/price_tag_tab.py for why: Unicode dingbat/arrow
        glyphs aren't reliably reachable via font-fallback on all systems,
        even when a plausible fallback font is technically installed.)"""
        scale = 4
        s = size * scale
        pm = QPixmap(s, s); pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(s * 0.12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = s * 0.22
        p.drawLine(int(m), int(m), int(s - m), int(s - m))
        p.drawLine(int(s - m), int(m), int(m), int(s - m))
        p.end()
        pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        return QIcon(pm)
