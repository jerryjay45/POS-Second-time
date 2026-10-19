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


# A receipt roll is never narrower than ~40 mm or wider than ~120 mm. A
# Generic / Text Only queue left on "Letter", "A4" or "Envelope B4" reports
# 216–250 mm; snapping that to the nearest receipt size (102 mm) gave far too many
# columns. Anything outside this range is rejected as "the driver doesn't know".
PLAUSIBLE_RECEIPT_MM = (40, 120)


def detect_reported_width_mm(printer_name: str = "") -> int | None:
    """Whatever width the OS driver reports, plausible or not (None if unknown)."""
    if not printer_name:
        return None
    system = platform.system()
    if system == "Windows":
        return _detect_windows(printer_name)
    if system == "Linux":
        return _detect_linux(printer_name)
    return None


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
    mm = detect_reported_width_mm(printer_name)
    if mm is None or not (PLAUSIBLE_RECEIPT_MM[0] <= mm <= PLAUSIBLE_RECEIPT_MM[1]):
        return None
    return mm


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


# ── Print queues + "printer check" ───────────────────────────────────────────

def list_print_queues() -> list[dict]:
    """Installed print queues as [{'name', 'driver', 'port'}]. Windows reads them
    with win32print; Linux uses lpstat (driver unknown). Never raises."""
    system = platform.system()
    out: list[dict] = []
    try:
        if system == "Windows":
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in win32print.EnumPrinters(flags, None, 2):
                out.append({"name": p.get("pPrinterName", ""),
                            "driver": p.get("pDriverName", ""),
                            "port": p.get("pPortName", "")})
        elif system == "Linux":
            import subprocess
            proc = subprocess.run(["lpstat", "-v"], capture_output=True, text=True, timeout=5)
            for line in proc.stdout.splitlines():
                m = re.match(r"device for (.+?):\s*(.*)$", line.strip())
                if m:
                    out.append({"name": m.group(1), "driver": "", "port": m.group(2)})
    except Exception:
        return out
    return out


def check_queue(name: str, mode: str, queues: list[dict] | None = None) -> list[tuple[str, str]]:
    """Plain-language findings about the chosen print queue: [(severity, text)],
    severity 'ok' | 'info' | 'warn'. `queues` can be passed in (tests)."""
    qs = list_print_queues() if queues is None else queues
    notes: list[tuple[str, str]] = []
    if not name.strip():
        notes.append(("info", "No printer chosen: receipts go to the Windows default printer."))
        return notes
    q = next((x for x in qs if x["name"].strip().lower() == name.strip().lower()), None)
    if q is None:
        if qs:
            notes.append(("warn", f"'{name}' is not one of the installed printers. "
                                  "Pick it from the list so receipts don't go nowhere."))
        else:
            notes.append(("info", "Could not list the installed printers on this PC."))
        return notes
    drv = (q.get("driver") or "").lower()
    text_only = "text only" in drv or drv.startswith("generic")
    port = q.get("port", "")
    if mode == "raster" and text_only:
        notes.append(("warn", f"'{q['name']}' uses a Generic / Text Only driver, which cannot print "
                              "graphics. Switch the print mode to Raw (plain text)."))
    elif mode == "raw" and text_only:
        notes.append(("ok", "Generic / Text Only driver with raw printing: the receipt is sent "
                            "straight to the printer. The queue's page size is ignored."))
    elif mode == "raw":
        notes.append(("ok", f"Raw printing: bytes go straight to the printer, so the driver's "
                            f"page size and margins don't apply ({q.get('driver') or 'driver unknown'})."))
    else:
        notes.append(("ok", f"Raster printing through '{q.get('driver') or 'the driver'}'. "
                            "The page size is set from the paper-width setting."))
    if port:
        notes.append(("info", f"Connected on {port}."))
    return notes
