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


def build_escpos_bytes(lines: list[tuple[str, str]], cut: bool = True, *,
                       font: str = "a", heading: str = "normal",
                       total: str = "normal") -> bytes | None:
    """
    lines — list of (text, kind) tuples from a *_lines() formatter
            function. kind is one of:
              "biz_name" — business name banner, centred and bold (size: see `heading`)
              "title"    — section banners (*** VOID ***, etc.), bold
              "total"    — the receipt's headline total, bold (size: see `total`)
              "div"      — divider rule, printed as-is
              "normal"   — everything else, printed as-is
    cut   — send a paper cut command at the end. Only pass True for
            printers with an automatic cutter — dot matrix printers
            like the TM-U220 have no cutter, and sending the command
            anyway risks garbled trailing output on printers that
            don't recognize it.
    font    — "a" (the printer's standard font, no command sent) or "b" (the
              compact font: ESC M 1, about 4/3 as many columns).
    heading — business-name size: "normal" (default: bold, normal size), "tall"
              (double height) or "double" (double height AND width; the formatter
              wraps the name at half width for it).
    total   — TOTAL-line size: "normal" (bold) or "tall" (double height).

    Returns the raw ESC/POS byte stream, or None if python-escpos isn't
    installed or fails to initialize for any reason — callers should
    fall back to plain ASCII text in that case rather than fail the
    print entirely.
    """
    try:
        from escpos.printer import Dummy
        d = Dummy()
        f = "b" if font == "b" else "a"

        def style(**kw):
            # python-escpos' set() puts back EVERYTHING you don't pass, so every
            # style change must carry Font B or a heading would silently drop the
            # printer back to Font A. Font A is passed as "nothing" on purpose:
            # naming it makes python-escpos send an explicit ESC M 0 that the
            # original receipts never contained.
            if f == "b":
                kw["font"] = "b"
            d.set(**kw)

        # Start every job from a known state (ESC @). Text size is sticky in
        # the printer, so a job that ever left it in double size would make
        # every later receipt - even plain-text ones - print huge. This must come
        # BEFORE the font is chosen: ESC @ puts the printer back to Font A.
        d.hw("INIT")

        if f == "b":
            style()                       # then select Font B once, up front

        for text, kind in lines:
            if kind == "biz_name":
                # Size is STICKY in the printer: whatever is set stays for every later
                # line (and later jobs) until it is explicitly put back. python-escpos'
                # set() only sends a size command when a size flag is True — passing
                # double_height=False does NOTHING — so the reset must use
                # normal_textsize=True. (Before this, the whole receipt printed in
                # double size after the business name.)
                big_h = heading in ("tall", "double")
                big_w = heading == "double"
                if big_h or big_w:
                    style(align="center", bold=True, double_height=big_h, double_width=big_w)
                else:
                    style(align="center", bold=True, normal_textsize=True)
                d.text(text.strip() + "\n")
                style(align="left", bold=False, normal_textsize=True)
            elif kind in ("title", "total"):
                tall = kind == "total" and total == "tall"
                if tall:
                    style(bold=True, double_height=True)
                else:
                    style(bold=True)                          # no size change: nothing to undo
                d.text(text + "\n")
                if tall:
                    style(bold=False, normal_textsize=True)   # a size WAS set: put it back
                else:
                    style(bold=False)
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
