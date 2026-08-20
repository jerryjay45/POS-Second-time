"""
utils/printer_capabilities.py
Paper-width lookup and auto-detection for the receipt printer.

Standard paper widths at 12 CPI (characters per inch), normal pitch:

    Paper   Typical use                     Columns (normal)
    57mm    Mobile / credit card terminals  32
    70mm    Healthcare, transport, ticketing 38
    76mm    Dot matrix (TM-U220)            40
    80mm    Retail / supermarket POS        42
    102mm   Specialized wide format         56

Public API
----------
STANDARD_WIDTHS_MM        — [57, 70, 76, 80, 102]
columns_for_width_mm(mm)  → int   (12 CPI, floored)
detect_paper_width_mm(printer_name) → int | None
    Queries the OS print driver for the configured paper width.
    Returns None if detection isn't possible (missing driver info,
    unsupported platform, generic/text-only driver, etc.) — callers
    should fall back to the saved/manual setting, not raise.
"""

from __future__ import annotations
import platform
import re

# Fallback is 76mm / 40 columns: it's the printer most setups actually have
# (dot matrix TM-U220), and 40 columns fits safely within every other
# paper size in the table below (only 57mm at compressed pitch matches
# it) — so a receipt formatted for the fallback never gets cut off on
# wider paper, it just leaves a larger margin.
DEFAULT_WIDTH_MM = 76
FALLBACK_COLUMNS = 40

STANDARD_WIDTHS_MM = [57, 70, 76, 80, 102]

# Real printable-area column counts per paper size at 12 CPI, normal pitch.
# Not a naive (width_mm / 25.4) * 12 calc — that overstates the printable
# width, since paper width includes margins the printer can't print into.
# These are the standard figures printer vendors publish for each size.
_KNOWN_COLUMNS = {57: 32, 70: 38, 76: 40, 80: 42, 102: 56}


def columns_for_width_mm(width_mm: float) -> int:
    """
    Column count for a given paper width, at 12 CPI normal pitch.
    Exact match against the standard sizes above when possible;
    otherwise snaps to the closest standard size's column count.
    """
    try:
        mm = float(width_mm)
    except (TypeError, ValueError):
        return FALLBACK_COLUMNS
    if mm in _KNOWN_COLUMNS:
        return _KNOWN_COLUMNS[mm]
    closest = min(_KNOWN_COLUMNS, key=lambda k: abs(k - mm))
    return _KNOWN_COLUMNS[closest]


def detect_paper_width_mm(printer_name: str = "") -> int | None:
    """
    Ask the OS print driver what paper width it's configured for.

    Windows — win32print DEVMODE.PaperWidth (tenths of a millimeter).
    Linux   — `lpoptions -p <printer> -l`, parses the PageSize/media option.
    macOS / anything else — not supported, returns None.

    Returns None (never raises) if the printer name is blank, the
    printer doesn't exist, the driver doesn't report a width, or the
    platform isn't supported — the caller should fall back to the
    saved/manual setting. Generic text-only drivers commonly report a
    default Letter/A4 size regardless of the actual roll installed, so
    this is a convenience, not a guarantee — the manual override always
    remains available.
    """
    if not printer_name:
        return None

    system = platform.system()

    if system == "Windows":
        return _detect_windows(printer_name)
    elif system == "Linux":
        return _detect_linux(printer_name)
    return None


def _detect_windows(printer_name: str) -> int | None:
    try:
        import win32print
    except ImportError:
        return None
    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            devmode = win32print.GetPrinter(hprinter, 2)["pDevMode"]
        finally:
            win32print.ClosePrinter(hprinter)
        if devmode is None or not getattr(devmode, "PaperWidth", None):
            return None
        # PaperWidth is in tenths of a millimeter
        return round(devmode.PaperWidth / 10)
    except Exception:
        return None


def _detect_linux(printer_name: str) -> int | None:
    try:
        import subprocess
        proc = subprocess.run(
            ["lpoptions", "-p", printer_name, "-l"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            return None
        # Look for a PageSize/media line, e.g.
        # "PageSize/Media Size: *Custom.76x297mm Letter A4 ..."
        for line in proc.stdout.splitlines():
            if line.lower().startswith(("pagesize", "media")):
                m = re.search(r"(\d+(?:\.\d+)?)\s*x\s*\d+(?:\.\d+)?mm", line)
                if m:
                    return round(float(m.group(1)))
        return None
    except Exception:
        return None
