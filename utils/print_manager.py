"""
utils/print_manager.py
Central print manager — all printing goes through here.

Public API
----------
print_receipt(receipt, parent)              — auto-prints at checkout
print_void(receipt, refund, user, parent)   — dialog for supervisor
print_refund(receipt, refund, user, parent) — dialog for supervisor
print_session(session, ..., parent)         — dialog for supervisor
reprint_receipt(receipt_number, parent)     — auto-prints to receipt printer
print_label(product, copies, printer, parent) — stub for future cash tab

Routing
-------
Auto-print (receipt, reprint):
  Uses ThermalPrinter (raw passthrough or raster, per receipt_printer_mode)
  → configured receipt printer or OS default. No dialog shown.
  In raw mode, if receipt_printer_escpos is enabled, sends real ESC/POS
  commands (bold headers/totals, paper cut, optional cash-drawer kick)
  via utils.escpos_builder instead of plain ASCII text.

Dialog-print (void, refund, session):
  Raw mode:    sends raw text/ESC-POS straight to the configured receipt
               printer, same as auto-print (no dialog — raw printers
               can't show one). Never kicks the cash drawer.
  Raster mode: uses QPrintPreviewDialog — user sees a preview and can pick
               any printer. Defaults to OS default printer.

All functions:
  - Return True on success, False on failure/cancel
  - Never raise — print errors never roll back transactions
  - Always save a .txt copy to receipts/ folder
"""

from __future__ import annotations
import os
import re
from datetime import datetime
from config import RECEIPT_DIR

# Receipts are filed per cashier, then by type:
#   receipts/<cashier>/transactions/   — sale receipts + reprints
#   receipts/<cashier>/voids/          — void notices
#   receipts/<cashier>/refunds/        — refund receipts
#   receipts/<cashier>/sessions/<report_type>/  — full / products / summary Z-reports
_UNKNOWN_CASHIER = "unknown_user"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_biz_and_currency() -> tuple[dict, str]:
    from core.db_config import get_business, get as cfg_get
    return get_business(), cfg_get("currency_symbol", "$")


def _safe_folder_name(name: str) -> str:
    """Sanitize a name for use as a filesystem folder (usernames, report types, etc.)."""
    name = (name or "").strip()
    if not name:
        return _UNKNOWN_CASHIER
    # Replace anything that isn't alphanumeric, dash, underscore, or space
    name = re.sub(r"[^\w\- ]+", "_", name)
    name = name.strip().replace(" ", "_")
    return name or _UNKNOWN_CASHIER


def _cashier_folder_by_user_id(user_id: int | None) -> str:
    """Resolve a user_id to a safe folder name (their username), falling back gracefully."""
    if user_id is None:
        return _UNKNOWN_CASHIER
    try:
        from core.db_users import get_user_by_id
        user = get_user_by_id(user_id)
        if user and user.get("username"):
            return _safe_folder_name(user["username"])
    except Exception as e:
        print(f"[PrintManager] Could not resolve cashier folder: {e}")
    return _UNKNOWN_CASHIER


def _save_text(subdirs: list[str], filename: str, text: str):
    """Save a .txt copy under receipts/<subdirs...>/filename."""
    folder = os.path.join(RECEIPT_DIR, *subdirs)
    os.makedirs(folder, exist_ok=True)
    try:
        with open(os.path.join(folder, filename), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"[PrintManager] Could not save text copy: {e}")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_num(receipt_number: str) -> str:
    return receipt_number.replace("#", "").replace("/", "-").strip()


def _auto_print(text: str, parent=None, lines: list | None = None,
                cash_drawer: bool = False) -> bool:
    """
    Print without a dialog using the configured receipt printer
    (raw passthrough or raster, per receipt_printer_mode).

    lines        — optional (text, kind) list from a *_lines() formatter
                   function. Only used in raw mode when
                   receipt_printer_escpos is enabled — builds a real
                   ESC/POS byte stream instead of plain text. Falls
                   back to plain text if python-escpos isn't installed
                   or lines wasn't provided.
    cash_drawer  — send a cash-drawer-open pulse (ESC/POS mode only).
                   Only ever pass True for a completed sale receipt.
    """
    from core.db_config import get as cfg_get
    from utils.thermal_printer import ThermalPrinter, PrinterError

    mode        = cfg_get("receipt_printer_mode", "raw").strip()
    use_escpos  = (mode == "raw" and lines is not None
                  and cfg_get("receipt_printer_escpos", "0").strip() == "1")

    try:
        with ThermalPrinter.from_config() as p:
            data = None
            if use_escpos:
                from utils.escpos_builder import build_escpos_bytes
                data = build_escpos_bytes(lines, cut=True, cash_drawer=cash_drawer)
            if data is not None:
                p.print_bytes(data)
            else:
                p.print_text(text)
        return True
    except PrinterError as e:
        print(f"[PrintManager] Auto-print error: {e}")
        if parent:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                parent, "Printer Error",
                f"{e}\n\nA text copy has been saved to the receipts folder."
            )
        return False
    except Exception as e:
        print(f"[PrintManager] Unexpected print error: {e}")
        return False


def _dialog_print(text: str, parent=None, lines: list | None = None) -> bool:
    """
    Print via dialog when possible. Raw mode has no preview to show (a raw
    spooler job isn't renderable), so it prints straight to the configured
    receipt printer, same as auto-print (never kicks the cash drawer —
    that's reserved for completed sales). Raster mode shows a
    QPrintPreviewDialog so the user can preview and pick any printer.
    """
    from core.db_config import get as cfg_get
    if cfg_get("receipt_printer_mode", "raw").strip() != "raster":
        return _auto_print(text, parent, lines=lines, cash_drawer=False)

    try:
        from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog
        from PyQt6.QtGui          import QPainter, QFont

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setColorMode(QPrinter.ColorMode.GrayScale)

        dlg = QPrintPreviewDialog(printer, parent)
        dlg.setWindowTitle("Print Preview")
        dlg.resize(900, 650)

        def _paint(preview_printer: QPrinter):
            painter = QPainter()
            try:
                if not painter.begin(preview_printer):
                    return
                font = QFont("Courier New", 9)
                font.setStyleHint(QFont.StyleHint.Monospace)
                painter.setFont(font)

                fm        = painter.fontMetrics()
                line_h    = fm.height() + 1
                page_rect = preview_printer.pageRect(QPrinter.Unit.DevicePixel)
                x         = int(page_rect.left()) + 10
                y_start   = int(page_rect.top())  + 10
                y_max     = int(page_rect.bottom()) - 10
                y         = y_start

                for line in text.split("\n"):
                    painter.drawText(x, y + fm.ascent(), line)
                    y += line_h
                    if y + line_h > y_max:
                        preview_printer.newPage()
                        y = y_start

                painter.end()
            except Exception as e:
                print(f"[PrintManager] Paint error: {e}")
                try: painter.end()
                except Exception: pass

        dlg.paintRequested.connect(_paint)
        result = dlg.exec()
        return result == QPrintPreviewDialog.DialogCode.Accepted

    except Exception as e:
        print(f"[PrintManager] Dialog print error: {e}")
        if parent:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(parent, "Printer Error", str(e))
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def print_receipt(receipt: dict, parent=None) -> bool:
    """Auto-print sale receipt at checkout — no dialog."""
    try:
        from core.db_config import get as cfg_get
        from utils.receipt_formatter import format_sale, format_sale_lines
        biz, currency = _get_biz_and_currency()
        lines = format_sale_lines(receipt, biz, currency)
        text  = "\n".join(t for t, _k in lines)
        cashier_folder = _cashier_folder_by_user_id(receipt.get("user_id"))
        _save_text([cashier_folder, "transactions"],
                   f"receipt_{_safe_num(receipt['receipt_number'])}_{_stamp()}.txt", text)

        cash_drawer = (
            cfg_get("cash_drawer_kick_on_cash_sale", "0").strip() == "1"
            and receipt["payment_method"] in ("cash", "split")
        )
        return _auto_print(text, parent, lines=lines, cash_drawer=cash_drawer)
    except Exception as e:
        print(f"[PrintManager] print_receipt error: {e}")
        return False


def print_void(receipt: dict, refund: dict,
               voided_by_user: dict = None, parent=None) -> bool:
    """Print void notice via preview dialog."""
    try:
        from utils.receipt_formatter import format_void_lines
        biz, currency = _get_biz_and_currency()
        voided_by = voided_by_user.get("full_name", "") if voided_by_user else ""
        reason    = refund.get("reason", "") if refund else ""
        lines = format_void_lines(receipt, biz, voided_by=voided_by,
                                  reason=reason, currency=currency)
        text  = "\n".join(t for t, _k in lines)
        cashier_folder = _cashier_folder_by_user_id(receipt.get("user_id"))
        _save_text([cashier_folder, "voids"],
                   f"void_{_safe_num(receipt['receipt_number'])}_{_stamp()}.txt", text)
        return _dialog_print(text, parent, lines=lines)
    except Exception as e:
        print(f"[PrintManager] print_void error: {e}")
        return False


def print_refund(receipt: dict, refund: dict,
                 refunded_by_user: dict = None, parent=None) -> bool:
    """Print refund receipt via preview dialog."""
    try:
        from utils.receipt_formatter import format_refund_lines
        biz, currency = _get_biz_and_currency()
        refunded_by = refunded_by_user.get("full_name", "") if refunded_by_user else ""
        reason      = refund.get("reason", "") if refund else ""
        amount      = refund.get("amount", receipt.get("total", 0))
        refund_type = refund.get("refund_type", "full") if refund else "full"
        lines = format_refund_lines(receipt, biz, refund_amount=amount,
                                    refund_type=refund_type, refunded_by=refunded_by,
                                    reason=reason, currency=currency)
        text  = "\n".join(t for t, _k in lines)
        cashier_folder = _cashier_folder_by_user_id(receipt.get("user_id"))
        _save_text([cashier_folder, "refunds"],
                   f"refund_{_safe_num(receipt['receipt_number'])}_{_stamp()}.txt", text)
        return _dialog_print(text, parent, lines=lines)
    except Exception as e:
        print(f"[PrintManager] print_refund error: {e}")
        return False


def print_session(session: dict, report_type: str = "full",
                  copies: int = 1, parent=None) -> bool:
    """Print session Z-report via preview dialog."""
    try:
        from utils.receipt_formatter import format_session_lines
        from core.db_checkout import (
            session_totals, session_group_totals,
            session_voided_receipts, get_session_receipts,
            get_receipt_by_id,
        )
        from core.db_users import get_user_by_id

        biz, currency = _get_biz_and_currency()
        totals    = session_totals(session["id"])
        grp_totals = session_group_totals(session["id"])
        voided    = session_voided_receipts(session["id"])

        all_receipts = None
        if report_type in ("full", "products"):
            receipts     = get_session_receipts(session["id"])
            all_receipts = [get_receipt_by_id(r["id"]) for r in receipts
                            if r.get("status") == "completed"]

        cashier      = get_user_by_id(session["user_id"])
        cashier_name = cashier["full_name"] if cashier else "Unknown"

        opened_by, closed_by = "", ""
        if session.get("opened_by"):
            u = get_user_by_id(session["opened_by"])
            opened_by = u["full_name"] if u else ""
        if session.get("closed_by"):
            u = get_user_by_id(session["closed_by"])
            closed_by = u["full_name"] if u else ""

        lines = format_session_lines(
            session, totals, cashier_name, biz,
            opened_by=opened_by, closed_by=closed_by,
            currency=currency, report_type=report_type,
            group_totals=grp_totals, voided_receipts=voided,
            all_receipts=all_receipts,
        )
        text = "\n".join(t for t, _k in lines)
        cashier_folder = _cashier_folder_by_user_id(session.get("user_id"))
        report_folder  = _safe_folder_name(report_type)
        _save_text([cashier_folder, "sessions", report_folder],
                   f"session_{session['id']:04d}_{report_type}_{_stamp()}.txt", text)
        return _dialog_print(text, parent, lines=lines)

    except Exception as e:
        print(f"[PrintManager] print_session error: {e}")
        return False


def reprint_receipt(receipt_number: str, parent=None) -> bool:
    """Reprint a past receipt — auto-prints to receipt printer, no dialog.
    Never kicks the cash drawer — that only fires on the original sale."""
    try:
        from core.db_checkout import get_receipt_by_number
        receipt = get_receipt_by_number(receipt_number)
        if not receipt:
            if parent:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(parent, "Not Found",
                    f"Receipt {receipt_number} not found.")
            return False
        from utils.receipt_formatter import format_sale_lines
        biz, currency = _get_biz_and_currency()
        lines = format_sale_lines(receipt, biz, currency)
        text  = "\n".join(t for t, _k in lines)
        cashier_folder = _cashier_folder_by_user_id(receipt.get("user_id"))
        _save_text([cashier_folder, "transactions"],
                   f"reprint_{_safe_num(receipt['receipt_number'])}_{_stamp()}.txt", text)
        return _auto_print(text, parent, lines=lines, cash_drawer=False)
    except Exception as e:
        print(f"[PrintManager] reprint_receipt error: {e}")
        return False


def print_label(product: dict, copies: int = 1,
                printer_name: str = "", parent=None) -> bool:
    """Stub — label printing handled by price tag tab UI."""
    try:
        from core.db_config import get as cfg_get
        if not printer_name:
            printer_name = cfg_get("label_printer_name", "")
        print(f"[Label] {product['name']} x{copies} → {printer_name or 'no printer'}")
        return True
    except Exception as e:
        print(f"[PrintManager] Label print error: {e}")
        return False
