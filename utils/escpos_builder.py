"""
utils/escpos_builder.py
Converts a receipt's styled line list (from receipt_formatter's
*_lines() functions) into real ESC/POS command bytes, using
python-escpos's Dummy device to build the byte stream offline (no
direct USB/serial connection needed — we're printing through the OS
spooler, same as plain raw text).

Only meaningful in raw mode with an ESC/POS-capable printer (TM-U220
and similar). Falls back gracefully: if python-escpos isn't installed,
or fails to initialize for any other reason (e.g. missing package data
in a frozen build), build_escpos_bytes() returns None and the caller
should send plain ASCII text instead.

Cash-drawer kicks are handled separately by drawer_kick_bytes() below,
not by python-escpos — the pulse is a fixed, well-known 5-byte command
that every drawer-capable receipt printer (thermal or dot matrix)
understands, so hand-writing it avoids pulling in the whole escpos
library just to open a drawer, and lets the kick fire as its own tiny
raw job independent of whichever mode the receipt itself printed in.
"""

from __future__ import annotations


def build_escpos_bytes(lines: list[tuple[str, str]], cut: bool = True) -> bytes | None:
    """
    lines — list of (text, kind) tuples from a *_lines() formatter
            function. kind is one of:
              "biz_name" — business name banner, bold + double size
              "title"    — section banners (*** VOID ***, etc.), bold
              "total"    — the receipt's headline total, bold
              "div"      — divider rule, printed as-is
              "normal"   — everything else, printed as-is
    cut   — send a paper cut command at the end. Only pass True for
            printers with an automatic cutter — dot matrix printers
            like the TM-U220 have no cutter, and sending the command
            anyway risks garbled trailing output on printers that
            don't recognize it.

    Returns the raw ESC/POS byte stream, or None if python-escpos isn't
    installed or fails to initialize for any reason — callers should
    fall back to plain ASCII text in that case rather than fail the
    print entirely.
    """
    try:
        from escpos.printer import Dummy
        d = Dummy()

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

        if cut:
            try:
                d.cut()
            except Exception:
                pass  # a cut failure shouldn't blank out an otherwise-good receipt

        return d.output
    except Exception:
        # Covers a missing python-escpos install, a missing/broken
        # capabilities.json (e.g. not bundled in a frozen build), or
        # any formatting error — all fall back to plain text rather
        # than failing the print entirely.
        return None


def drawer_kick_bytes(pin: int = 2) -> bytes:
    """
    The standard ESC/POS cash-drawer-open pulse: ESC p m t1 t2.
    Hand-written rather than routed through python-escpos, so a drawer
    kick never depends on that library being installed or initializing
    correctly — it's a fixed 5-byte sequence understood by effectively
    every receipt printer (thermal or dot matrix) with a drawer port,
    wired or not.

    pin — which connector pin to pulse: 2 (default, byte 0x00) or
          5 (byte 0x01). Which one fires the drawer depends on how the
          drawer cable is wired into the printer's RJ11/RJ12 port, not
          on anything this app can detect — 2 is the common default.
    """
    m = 0x00 if pin != 5 else 0x01
    return bytes([0x1B, 0x70, m, 50, 50])
