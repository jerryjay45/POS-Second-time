"""
main.py — Merchant POS Systems entry point.
Run with:  python main.py
"""
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Create required directories
from config import DATA_DIR, RECEIPT_DIR, LABEL_DIR
os.makedirs(DATA_DIR,    exist_ok=True)
os.makedirs(RECEIPT_DIR, exist_ok=True)
os.makedirs(LABEL_DIR,   exist_ok=True)

# Initialise all databases
from core import init_all_databases
init_all_databases()

# High-DPI policy MUST be set before QApplication is created
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore    import Qt, pyqtSignal, QObject

# App-level signal bus — lets supervisor broadcast session closure to cashier windows
class _AppSignals(QObject):
    session_closed = pyqtSignal(int)   # emits session_id
    session_opened = pyqtSignal(int)   # emits user_id of the cashier

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Merchant POS Systems")
    app.setApplicationVersion("1.0.0")

    # Attach signal bus so any window can broadcast/listen
    app._signals = _AppSignals()
    app.session_closed = app._signals.session_closed
    app.session_opened = app._signals.session_opened

    # Set base application font — everything scales from this
    from PyQt6.QtGui import QFont, QFontDatabase
    font_dir = os.path.join(os.path.dirname(__file__), "assets", "fonts")
    if os.path.isdir(font_dir):
        for f in os.listdir(font_dir):
            if f.endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, f))
    base_font = QFont("Inter")
    base_font.setPointSize(10)   # base size — stylesheet sizes are relative to this
    base_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(base_font)

    # Apply theme stylesheet
    from ui.shared.theme import apply_theme, get_stylesheet
    from core.db_config import get as cfg_get
    apply_theme(cfg_get("theme", "amber"))
    app.setStyleSheet(get_stylesheet())

    # Show setup wizard on first run (no manager account exists)
    from ui.setup_wizard import SetupWizard
    if SetupWizard.needs_setup():
        wizard = SetupWizard()
        if wizard.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)   # user closed wizard without completing

    # Show login window
    from ui.login_window import LoginWindow
    window = LoginWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
