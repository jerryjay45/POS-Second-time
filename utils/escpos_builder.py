"""
utils/escpos_builder.py
Converts a receipt's styled line list (from receipt_formatter's
*_lines() functions) into real ESC/POS command bytes, using
python-escpos's Dummy device to build the byte stream offline (no
direct USB/serial connection needed — we're printing through the OS
spooler, same as plain raw text).

Only meaningful in raw mode with an ESC/POS-capable printer (TM-U220
and similar). Falls back gracefully: if python-escpos isn't installed,
build_escpos_bytes() returns None and the caller should send plain
ASCII text instead.
"""

from __future__ import annotations


def build_escpos_bytes(lines: list[tuple[str, str]], cut: bool = True,
                        cash_drawer: bool = False) -> bytes | None:
    """
    lines       — list of (text, kind) tuples from a *_lines() formatter
                  function. kind is one of:
                    "biz_name" — business name banner, bold + double size
                    "title"    — section banners (*** VOID ***, etc.), bold
                    "total"    — the receipt's headline total, bold
                    "div"      — divider rule, printed as-is
                    "normal"   — everything else, printed as-is
    cut         — send a paper cut command at the end.
    cash_drawer — send a cash-drawer-open pulse at the end (before the
                  cut). Only meaningful if the drawer is wired through
                  the printer, which is the common setup.

    Returns the raw ESC/POS byte stream, or None if python-escpos isn't
    installed — callers should fall back to plain ASCII text in that case.
    """
    try:
        from escpos.printer import Dummy
    except ImportError:
        return None

    d = Dummy()
    try:
        for text, kind in lines:
            if kind == "biz_name":
                d.set(align="center", bold=True, double_height=True, double_width=True)
                d.text(text.strip() + "\n")
                d.set(align="left", bold=False, double_height=False, double_width=False)
            elif kind in ("title", "total"):
                d.set(bold=True)
                d.text(text + "\n")
                d.set(bold=False)
            else:
                d.text(text + "\n")

        if cash_drawer:
            try:
                d.cashdraw(2)
            except Exception:
                pass  # drawer kick is best-effort — never block the receipt print

        if cut:
            try:
                d.cut()
            except Exception:
                pass

        return d.output
    except Exception:
        # Any formatting error falls back to plain text rather than
        # failing the print entirely.
        return None
