"""
ui/setup_wizard.py
First-time setup wizard — shown on first launch when no manager account exists.

Pages:
  0  Welcome
  1  Business Info
  2  Tax & Currency
  3  Manager Account
  4  Printer  (optional)
  5  Done
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFrame, QStackedWidget,
    QCheckBox, QDoubleSpinBox, QTextEdit, QProgressBar,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_2, DARK_CARD,
    WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT,
    RED, GREEN, GREEN_LIGHT,
)


# ── Shared style helpers ──────────────────────────────────────────────────────

def _input(placeholder="", password=False, h=38, uppercase=True):
    inp = QLineEdit()
    inp.setPlaceholderText(placeholder)
    inp.setFixedHeight(h)
    if password:
        inp.setEchoMode(QLineEdit.EchoMode.Password)
    elif uppercase:
        inp.textChanged.connect(
            lambda t: inp.setText(t.upper()) if t != t.upper() else None
        )
    inp.setStyleSheet(
        f"QLineEdit{{background:{WHITE};color:{DARK_CARD};"
        f"border:1px solid {BORDER};border-radius:8px;"
        f"padding:0 12px;font-size:13px;}}"
        f"QLineEdit:focus{{border-color:{AMBER};}}"
    )
    return inp

def _label(text, size=12, bold=False, color=None):
    l = QLabel(text)
    style = f"color:{color or DARK_CARD};font-size:{size}px;"
    if bold:
        style += "font-weight:700;"
    l.setStyleSheet(style)
    return l

def _field_label(text):
    l = QLabel(text)
    l.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;")
    return l

def _div():
    d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
    d.setStyleSheet(f"background:{BORDER_LIGHT};max-height:1px;border:none;")
    return d


# ── Individual page widgets ───────────────────────────────────────────────────

class _WelcomePage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(16)
        lay.addStretch()

        logo = QLabel("🛒")
        logo.setStyleSheet("font-size:56px;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)

        title = QLabel("Welcome to\nMerchant POS Systems")
        title.setStyleSheet(
            f"color:{DARK_CARD};font-size:22px;font-weight:800;"
            f"line-height:1.3;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        sub = QLabel(
            "This wizard will help you set up your POS system.\n"
            "It only takes a few minutes."
        )
        sub.setStyleSheet(f"color:{MUTED};font-size:13px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)

        lay.addStretch()

    def collect(self) -> dict:
        return {}

    def validate(self) -> str | None:
        return None


class _BusinessPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(10)

        lay.addWidget(_label("Business Information", 16, bold=True))
        lay.addWidget(_label("This appears on receipts and price tags.", color=MUTED))
        lay.addWidget(_div())

        fields = [
            ("Business Name *", "e.g. JOHN'S SUPERMARKET", False),
            ("Address",         "e.g. 12 Main Street, Kingston", False),
            ("Phone",           "e.g. 876-555-0100", False),
            ("Email",           "e.g. info@business.com", False),
            ("TRN / Tax ID",    "e.g. 123-456-789", False),
        ]
        self._inputs = {}
        keys = ["name", "address", "phone", "email", "tax_id"]
        for (lbl, ph, pw), key in zip(fields, keys):
            lay.addWidget(_field_label(lbl))
            inp = _input(ph, pw)
            self._inputs[key] = inp
            lay.addWidget(inp)

        lay.addWidget(_field_label("Receipt Footer"))
        self.footer = QTextEdit()
        self.footer.setPlaceholderText("e.g. Thank you for your business!")
        self.footer.setFixedHeight(60)
        self.footer.setStyleSheet(
            f"QTextEdit{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:8px;padding:8px;}}"
            f"QTextEdit:focus{{border-color:{AMBER};}}"
        )
        self.footer.setPlainText("THANK YOU FOR YOUR BUSINESS!")
        self.footer.textChanged.connect(
            lambda: (self.footer.blockSignals(True),
                     self.footer.setPlainText(self.footer.toPlainText().upper()),
                     self.footer.moveCursor(self.footer.textCursor().End),
                     self.footer.blockSignals(False))
            if self.footer.toPlainText() != self.footer.toPlainText().upper() else None
        )
        lay.addWidget(self.footer)
        lay.addStretch()

    def collect(self) -> dict:
        return {
            "name":           self._inputs["name"].text().strip(),
            "address":        self._inputs["address"].text().strip(),
            "phone":          self._inputs["phone"].text().strip(),
            "email":          self._inputs["email"].text().strip(),
            "tax_id":         self._inputs["tax_id"].text().strip(),
            "receipt_footer": self.footer.toPlainText().strip(),
        }

    def validate(self) -> str | None:
        if not self._inputs["name"].text().strip():
            return "Business Name is required."
        return None


class _TerminalPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(14)

        title = QLabel("Terminal Identity")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:17px;font-weight:800;")
        lay.addWidget(title)

        desc = QLabel(
            "Each POS terminal needs a unique ID so receipts from different "
            "terminals never clash. Use a short code like T01, T02, or a "
            "location name like MAIN or COUNTER2."
        )
        desc.setStyleSheet(f"color:{MUTED};font-size:12px;")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        lay.addSpacing(6)

        id_lbl = QLabel("Terminal ID  *")
        id_lbl.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;font-weight:600;")
        lay.addWidget(id_lbl)
        self.terminal_id = _input("e.g. T01  or  MAIN  or  COUNTER2")
        self.terminal_id.setMaxLength(10)
        lay.addWidget(self.terminal_id)

        hint = QLabel(
            "Max 10 characters. Letters and numbers only.\n"
            "This will appear on every receipt:  T01-0001,  T01-0002 …"
        )
        hint.setStyleSheet(f"color:{MUTED};font-size:10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()

    def collect(self) -> dict:
        return {"terminal_id": self.terminal_id.text().strip()}

    def validate(self) -> str | None:
        tid = self.terminal_id.text().strip()
        if not tid:
            return "Terminal ID is required."
        if not tid.replace("-", "").isalnum():
            return "Terminal ID must contain only letters and numbers."
        return None


class _TaxPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        lay.addWidget(_label("Tax & Currency", 16, bold=True))
        lay.addWidget(_label("Configure your local tax and currency settings.", color=MUTED))
        lay.addWidget(_div())

        # Currency symbol
        lay.addWidget(_field_label("Currency Symbol"))
        self.currency = _input("e.g. $  or  J$", uppercase=False)
        self.currency.setText("$")
        lay.addWidget(self.currency)

        # GCT toggle
        gct_row = QHBoxLayout(); gct_row.setSpacing(10)
        self.gct_enabled = QCheckBox("Enable GCT (General Consumption Tax)")
        self.gct_enabled.setChecked(True)
        self.gct_enabled.setStyleSheet(
            f"QCheckBox{{color:{DARK_CARD};font-size:13px;}}"
            f"QCheckBox::indicator{{width:16px;height:16px;"
            f"border:1.5px solid {BORDER};border-radius:4px;background:{WHITE};}}"
            f"QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}"
        )
        gct_row.addWidget(self.gct_enabled); gct_row.addStretch()
        lay.addLayout(gct_row)

        # GCT rate
        lay.addWidget(_field_label("GCT Rate (%)"))
        self.gct_rate = QDoubleSpinBox()
        self.gct_rate.setRange(0, 50)
        self.gct_rate.setDecimals(2)
        self.gct_rate.setValue(16.5)
        self.gct_rate.setSuffix("  %")
        self.gct_rate.setFixedHeight(38)
        self.gct_rate.setFixedWidth(140)
        self.gct_rate.setStyleSheet(
            f"QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:8px;"
            f"padding:0 10px;font-size:13px;}}"
            f"QDoubleSpinBox:focus{{border-color:{AMBER};}}"
        )
        lay.addWidget(self.gct_rate)

        note = QLabel("GCT will be added to products marked as GCT-applicable at checkout.")
        note.setStyleSheet(f"color:{MUTED};font-size:11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()

    def collect(self) -> dict:
        return {
            "currency_symbol": self.currency.text().strip() or "$",
            "gct_enabled":     "1" if self.gct_enabled.isChecked() else "0",
            "gct_rate":        str(self.gct_rate.value() / 100),
        }

    def validate(self) -> str | None:
        return None


class _ManagerPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(10)

        lay.addWidget(_label("Manager Account", 16, bold=True))
        lay.addWidget(_label(
            "Create the first manager account. This account has full access to all settings.",
            color=MUTED
        ))
        lay.addWidget(_div())

        fields = [
            ("Full Name *",       "e.g. John Smith",   False, "full_name"),
            ("Username *",        "e.g. MANAGER",      False, "username"),
            ("Password *",        "Min. 4 characters", True,  "password"),
            ("Confirm Password *","Re-enter password", True,  "confirm"),
        ]
        self._inputs = {}
        for lbl, ph, pw, key in fields:
            lay.addWidget(_field_label(lbl))
            inp = _input(ph, pw)
            self._inputs[key] = inp
            lay.addWidget(inp)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet(f"color:{RED};font-size:11px;")
        lay.addWidget(self.err_lbl)
        lay.addStretch()

    def collect(self) -> dict:
        return {
            "full_name": self._inputs["full_name"].text().strip(),
            "username":  self._inputs["username"].text().strip(),
            "password":  self._inputs["password"].text(),
        }

    def validate(self) -> str | None:
        d = self.collect()
        if not d["full_name"]:
            return "Full Name is required."
        if not d["username"]:
            return "Username is required."
        if not d["password"]:
            return "Password is required."
        if len(d["password"]) < 4:
            return "Password must be at least 4 characters."
        if d["password"] != self._inputs["confirm"].text():
            return "Passwords do not match."
        self.err_lbl.setText("")
        return None


class _PrinterPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        lay.addWidget(_label("Printer Setup", 16, bold=True))
        lay.addWidget(_label("Optional — you can configure this later in Manager Settings.", color=MUTED))
        lay.addWidget(_div())

        # Receipt printer
        lay.addWidget(_field_label("Receipt Printer"))
        self.thermal = _input("e.g. EPSON TM-U220 — as it appears in your OS printer list", uppercase=False)
        lay.addWidget(self.thermal)
        hint1 = QLabel(
            "Enter the printer's name exactly as installed in your OS, or leave "
            "blank to use the OS default printer. You can fine-tune the print "
            "mode and paper width later in Manager → Settings → Printers."
        )
        hint1.setStyleSheet(f"color:{MUTED};font-size:10px;"); hint1.setWordWrap(True)
        lay.addWidget(hint1)

        lay.addSpacing(8)

        # Copies
        lay.addWidget(_field_label("Receipt Copies"))
        copies_row = QHBoxLayout(); copies_row.setSpacing(8)
        self.copies = QDoubleSpinBox()
        self.copies.setRange(1, 5)
        self.copies.setDecimals(0)
        self.copies.setValue(1)
        self.copies.setFixedHeight(38); self.copies.setFixedWidth(80)
        self.copies.setStyleSheet(
            f"QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:8px;padding:0 10px;font-size:13px;}}"
            f"QDoubleSpinBox:focus{{border-color:{AMBER};}}"
        )
        copies_row.addWidget(self.copies); copies_row.addStretch()
        lay.addLayout(copies_row)

        lay.addStretch()

    def collect(self) -> dict:
        return {
            "receipt_printer_name": self.thermal.text().strip(),
            "receipt_copies":       str(int(self.copies.value())),
        }

    def validate(self) -> str | None:
        return None


class _DonePage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(16)
        lay.addStretch()

        icon = QLabel("✅")
        icon.setStyleSheet("font-size:52px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)

        title = QLabel("You're all set!")
        title.setStyleSheet(
            f"color:{DARK_CARD};font-size:22px;font-weight:800;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{MUTED};font-size:12px;"
            f"background:{WARM_WHITE};border:1px solid {BORDER};"
            f"border-radius:8px;padding:14px 18px;"
        )
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.summary)

        lay.addStretch()

    def set_summary(self, biz_name: str, username: str, printer: str,
                    terminal_id: str = ""):
        lines = [
            f"✓  Business: {biz_name}",
            f"✓  Terminal ID: {terminal_id or '—'}",
            f"✓  Manager account: {username}",
        ]
        if printer:
            lines.append(f"✓  Printer: {printer}")
        else:
            lines.append("—  Printer: not configured (set in Manager → Settings)")
        lines.append("\nYou can change any of these settings at any time from the Manager dashboard.")
        self.summary.setText("\n".join(lines))

    def collect(self) -> dict:
        return {}

    def validate(self) -> str | None:
        return None


# ── SetupWizard ───────────────────────────────────────────────────────────────

class SetupWizard(QDialog):
    """
    Modal first-time setup wizard.
    Call SetupWizard.needs_setup() to check if it should be shown.
    Exec and check result before showing the login window.
    """

    _PAGE_TITLES = [
        "Welcome",
        "Business Info",
        "Terminal",
        "Tax & Currency",
        "Manager Account",
        "Printer",
        "Done",
    ]

    @staticmethod
    def needs_setup() -> bool:
        """Return True if no manager account exists — first run."""
        try:
            from core.db_users import get_users
            managers = get_users(role="manager")
            return len(managers) == 0
        except Exception:
            return True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merchant POS — Setup Wizard")
        self.setMinimumSize(540, 580)
        self.setMaximumSize(640, 680)
        self.setModal(True)
        self.setStyleSheet(f"background:{WHITE};")
        self._current = 0
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(64)
        top.setStyleSheet(f"background:{DARK};border-bottom:2px solid {AMBER};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(24, 0, 24, 0)
        self.top_title = QLabel("Welcome")
        self.top_title.setStyleSheet(
            f"color:white;font-size:16px;font-weight:700;"
        )
        tl.addWidget(self.top_title)
        tl.addStretch()
        self.step_lbl = QLabel("Step 1 of 6")
        self.step_lbl.setStyleSheet(f"color:{AMBER};font-size:11px;font-weight:600;")
        tl.addWidget(self.step_lbl)
        root.addWidget(top)

        # Progress bar
        self.prog = QProgressBar()
        self.prog.setRange(0, len(self._PAGE_TITLES) - 1)
        self.prog.setValue(0)
        self.prog.setFixedHeight(4)
        self.prog.setTextVisible(False)
        self.prog.setStyleSheet(
            f"QProgressBar{{background:{DARK_2};border:none;}}"
            f"QProgressBar::chunk{{background:{AMBER};}}"
        )
        root.addWidget(self.prog)

        # ── Pages ─────────────────────────────────────────────────────
        self._pages = [
            _WelcomePage(),
            _BusinessPage(),
            _TerminalPage(),
            _TaxPage(),
            _ManagerPage(),
            _PrinterPage(),
            _DonePage(),
        ]
        self._stack = QStackedWidget()
        for p in self._pages:
            self._stack.addWidget(p)
        root.addWidget(self._stack, stretch=1)

        # ── Error label ───────────────────────────────────────────────
        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet(
            f"color:{RED};font-size:11px;font-weight:600;"
            f"padding:4px 24px;"
        )
        root.addWidget(self.err_lbl)

        # ── Bottom nav ────────────────────────────────────────────────
        bot = QFrame()
        bot.setStyleSheet(
            f"background:{WARM_WHITE};border-top:1px solid {BORDER};"
        )
        bl = QHBoxLayout(bot)
        bl.setContentsMargins(24, 12, 24, 12)
        bl.setSpacing(10)

        self.back_btn = QPushButton("← Back")
        self.back_btn.setFixedHeight(40)
        self.back_btn.setFixedWidth(100)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{LABEL_TEXT};"
            f"border:1.5px solid {BORDER};border-radius:8px;"
            f"font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}"
        )
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self._go_back)

        bl.addWidget(self.back_btn)
        bl.addStretch()

        self.next_btn = QPushButton("Next →")
        self.next_btn.setFixedHeight(40)
        self.next_btn.setFixedWidth(130)
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(
            f"QPushButton{{background:{AMBER};color:white;border:none;"
            f"border-radius:8px;font-size:13px;font-weight:700;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};}}"
        )
        self.next_btn.clicked.connect(self._go_next)
        bl.addWidget(self.next_btn)
        root.addWidget(bot)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go_next(self):
        page = self._pages[self._current]
        err  = page.validate()
        if err:
            self.err_lbl.setText(err)
            return
        self.err_lbl.setText("")

        last = len(self._pages) - 1

        # On last page, close
        if self._current == last:
            self.accept()
            return

        # Commit page data when leaving it
        self._commit_page(self._current, page.collect())

        # On second-to-last (printer), build done summary
        if self._current == last - 1:
            biz = self._pages[1].collect()
            tid = self._pages[2].collect()
            mgr = self._pages[4].collect()
            ptr = self._pages[5].collect()
            self._pages[last].set_summary(
                biz.get("name", "—"),
                mgr.get("username", "—").upper(),
                ptr.get("receipt_printer_name", ""),
                tid.get("terminal_id", ""),
            )

        self._current += 1
        self._stack.setCurrentIndex(self._current)
        self._update_nav()

    def _go_back(self):
        if self._current > 0:
            self._current -= 1
            self._stack.setCurrentIndex(self._current)
            self.err_lbl.setText("")
            self._update_nav()

    def _update_nav(self):
        last = len(self._pages) - 1
        self.back_btn.setEnabled(self._current > 0)
        self.next_btn.setText("Launch POS →" if self._current == last else "Next →")
        self.top_title.setText(self._PAGE_TITLES[self._current])
        self.step_lbl.setText(f"Step {self._current + 1} of {len(self._pages)}")
        self.prog.setValue(self._current)

    # ── Data commit ───────────────────────────────────────────────────────────

    def _commit_page(self, page_idx: int, data: dict):
        """Write page data to the DB immediately when the user moves past it."""
        try:
            if page_idx == 1 and data:   # Business info
                from core.db_config import update_business
                update_business(**{k: v for k, v in data.items() if v})

            elif page_idx == 2 and data:   # Terminal ID
                from core.db_config import set_many
                tid = data.get("terminal_id", "").strip().upper()
                if tid:
                    set_many({"terminal_id": tid})

            elif page_idx == 3 and data:   # Tax & currency
                from core.db_config import set_many
                set_many(data)

            elif page_idx == 4 and data:   # Manager account
                from core.db_users import get_users, add_user
                if not get_users(role="manager"):
                    add_user(
                        full_name=data["full_name"],
                        username=data["username"],
                        password=data["password"],
                        role="manager",
                    )

            elif page_idx == 5 and data:   # Printer
                from core.db_config import set_many
                settings = {}
                if data.get("receipt_printer_name"):
                    settings["receipt_printer_name"] = data["receipt_printer_name"]
                if data.get("receipt_copies"):
                    settings["receipt_copies"] = data["receipt_copies"]
                if settings:
                    set_many(settings)

        except Exception as e:
            self.err_lbl.setText(f"Could not save: {e}")
