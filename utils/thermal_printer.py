"""
utils/thermal_printer.py
The single receipt printer driver — used for every receipt, void,
refund, and session print.

Two print modes (see core.db_config "receipt_printer_mode"):

    "raw"     Sends plain text straight to the OS print spooler,
              bypassing raster rendering entirely. Required for dot
              matrix printers on a generic text-only driver (e.g.
              Epson TM-U220) and works for ESC/POS thermal printers
              too. Windows: win32print. Linux/macOS: `lpr -l`.

    "raster"  Renders text with QPrinter/QPainter, same as printing to
              any normal OS-managed printer (handles fonts, page
              breaks, and non-text-only drivers).

If no printer name is configured, the OS default printer is used.

Usage:
    with ThermalPrinter.from_config() as p:
        p.print_text(text)
"""

from __future__ import annotations


class PrinterError(Exception):
    """Raised when printing fails."""


RASTER_ROLL_LENGTH_MM = 2000     # "long roll": the page ends when the job does


def configure_raster_page(printer, width_mm: float, length_mm: float = RASTER_ROLL_LENGTH_MM):
    """Give a QPrinter an explicit receipt-sized page (width from the paper
    setting, a long roll length, zero margins) instead of whatever page size the
    Windows queue happens to be set to."""
    from PyQt6.QtCore import QSizeF, QMarginsF
    from PyQt6.QtGui import QPageSize, QPageLayout
    size = QPageSize(QSizeF(float(width_mm), float(length_mm)),
                     QPageSize.Unit.Millimeter, "Receipt")
    printer.setPageSize(size)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)


RASTER_MAX_FONT_PT = 12.0         # a receipt never needs bigger than this


def fit_font_to_columns(font, painter, printer, columns: int, pad_px: int = 20,
                        paper_width_mm: float | None = None):
    """Shrink/grow `font` so `columns` characters fit across the printable width.

    The width used is the *smaller* of what the driver reports and the paper
    width configured in the receipt settings. Without that cap, a queue left on
    Letter/A4 reports a page 200+ mm wide, the search grows the font until 40
    columns fill it, and the receipt prints huge. The point size is also capped
    at RASTER_MAX_FONT_PT as a last line of defence."""
    from PyQt6.QtGui import QFontMetrics
    page_w = printer.pageRect(printer.Unit.DevicePixel).width()
    if paper_width_mm:
        try:
            dpi = printer.resolution()
            if dpi > 0:
                page_w = min(page_w, float(paper_width_mm) / 25.4 * dpi)
        except Exception:
            pass
    page_w -= pad_px
    if page_w <= 0 or columns <= 0:
        return font
    sample = "0" * int(columns)
    lo, hi, best = 4.0, RASTER_MAX_FONT_PT, 9.0
    for _ in range(14):                       # binary search on point size
        mid = (lo + hi) / 2
        font.setPointSizeF(mid)
        if QFontMetrics(font, printer).horizontalAdvance(sample) <= page_w:
            best, lo = mid, mid
        else:
            hi = mid
    font.setPointSizeF(best)
    return font


class ThermalPrinter:
    """
    Context manager — open/close handled automatically.

        with ThermalPrinter.from_config() as p:
            p.print_text(text)

    If printer_name is blank the OS default printer is used.
    """

    def __init__(self, printer_name: str = "", copies: int = 1,
                 mode: str = "raw", form_feed: bool = True,
                 paper_width_mm: float = 76, columns: int = 40,
                 raster_pt: int | None = None):
        self._name   = printer_name.strip()
        self._copies = max(1, copies)
        self._mode   = mode if mode in ("raw", "raster") else "raw"
        self._form_feed = form_feed
        self._paper_width_mm = paper_width_mm
        self._columns = columns
        self._raster_pt = raster_pt          # None = fit the columns to the paper

    # ── Factory ───────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, copies: int | None = None) -> "ThermalPrinter":
        """Build from the settings DB. `copies` overrides the saved "copies per sale" for
        this one job (a report asks for its own number; sales use the saved setting)."""
        try:
            from core.db_config import get as cfg_get
            name   = cfg_get("receipt_printer_name", "").strip()
            mode   = cfg_get("receipt_printer_mode", "raw").strip()
            saved  = int(cfg_get("receipt_copies", "1") or "1")
        except Exception:
            name, mode, saved = "", "raw", 1
        copies = saved if copies is None else copies
        form_feed, mm, cols, pt = True, 76, 40, None
        try:
            from utils.receipt_layout import load_layout
            lay = load_layout()
            form_feed, cols, pt = lay.form_feed, lay.columns, lay.raster_pt
            mm = float(cfg_get("receipt_paper_width_mm", "76") or 76)
        except Exception:
            pass
        return cls(name, copies, mode, form_feed, mm, cols, pt)

    # ── Context manager ───────────────────────────────────────────────

    def __enter__(self) -> "ThermalPrinter":
        return self

    def __exit__(self, *_):
        pass

    # ── Public API ────────────────────────────────────────────────────

    def print_text(self, text: str) -> "ThermalPrinter":
        """Print plain text. Called once per receipt."""
        for _ in range(self._copies):
            if self._mode == "raster":
                self._print_raster(text)
            else:
                self._print_raw(text)
        return self

    def print_bytes(self, data: bytes) -> "ThermalPrinter":
        """
        Send a pre-built raw byte stream straight to the spooler (e.g. an
        ESC/POS command stream from utils.escpos_builder). Raw-mode only —
        a byte stream can't be rasterized, so this ignores print mode and
        always goes straight to the spooler.
        """
        for _ in range(self._copies):
            self._send_raw(data)
        return self

    def cut(self) -> "ThermalPrinter":
        """No-op — paper cut is handled by the printer driver/form feed."""
        return self

    def kick_drawer(self, pin: int = 2) -> "ThermalPrinter":
        """
        Fire the cash-drawer-open pulse as its own tiny raw job, straight
        to the OS spooler — independent of print mode. A raster-mode
        receipt still renders as a normal document (the pulse can't be
        embedded in that), but the drawer itself is opened by this
        separate, short raw byte send to the same printer queue, exactly
        like the ESC/POS-formatted raw text path already uses.

        Sent once regardless of the configured copy count — kicking the
        drawer twice per sale would be a bug, not a feature.
        """
        from utils.escpos_builder import drawer_kick_bytes
        self._send_raw(drawer_kick_bytes(pin))
        return self

    # ── Properties ────────────────────────────────────────────────────

    @property
    def is_configured(self) -> bool:
        """Always True — blank name uses OS default."""
        return True

    @property
    def connection_type(self) -> str:
        return f"os_driver_{self._mode}"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def copies(self) -> int:
        return self._copies

    # ── Raw text passthrough ─────────────────────────────────────────

    def _print_raw(self, text: str):
        """
        Send plain text directly to the printer spooler — bypasses
        QPrinter's raster rendering entirely. Required for dot matrix
        printers using generic text-only drivers.
        """
        lines = text.replace("\r\n", "\n").replace("\r", "\n")
        # The trailing newline ends the last line; the form feed is optional
        # (a roll printer has no pages — see the "form feed" setting).
        raw   = (lines + ("\n\f" if self._form_feed else "\n")).encode("ascii", errors="replace")
        self._send_raw(raw)

    def _send_raw(self, raw: bytes):
        """Send a raw byte buffer straight to the OS print spooler."""
        import platform

        if platform.system() == "Windows":
            try:
                import win32print
            except ImportError as e:
                raise PrinterError(f"win32print not installed: {e}")
            try:
                pname = self._name or win32print.GetDefaultPrinter()
                hprinter = win32print.OpenPrinter(pname)
                try:
                    hjob = win32print.StartDocPrinter(hprinter, 1, ("Receipt", None, "RAW"))
                    try:
                        win32print.StartPagePrinter(hprinter)
                        win32print.WritePrinter(hprinter, raw)
                        win32print.EndPagePrinter(hprinter)
                    finally:
                        win32print.EndDocPrinter(hprinter)
                finally:
                    win32print.ClosePrinter(hprinter)
            except Exception as e:
                raise PrinterError(str(e))
        else:
            # Linux / macOS — use lpr with passthrough flag
            try:
                import subprocess
                cmd = ["lpr", "-l"]
                if self._name:
                    cmd += ["-P", self._name]
                proc = subprocess.run(cmd, input=raw, capture_output=True, timeout=10)
                if proc.returncode != 0:
                    err = proc.stderr.decode(errors="replace")
                    raise PrinterError(f"lpr error: {err}")
            except PrinterError:
                raise
            except Exception as e:
                raise PrinterError(str(e))

    # ── Raster (QPrinter/QPainter) ───────────────────────────────────

    def _print_raster(self, text: str):
        try:
            from PyQt6.QtPrintSupport import QPrinter
            from PyQt6.QtGui          import QPainter, QFont
        except ImportError as e:
            raise PrinterError(f"PyQt6 not available: {e}")

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setColorMode(QPrinter.ColorMode.GrayScale)
        printer.setCopyCount(1)   # we loop copies ourselves

        if self._name:
            printer.setPrinterName(self._name)
        # else: QPrinter uses OS default automatically

        # Don't trust the Windows queue's page size (a queue left on Letter/A4/B4
        # would print a full sheet per receipt): use the configured paper width.
        configure_raster_page(printer, self._paper_width_mm)

        painter = QPainter()
        try:
            if not painter.begin(printer):
                raise PrinterError(
                    f"Could not open printer"
                    f"{': ' + self._name if self._name else ' (OS default)'}.\n"
                    f"Check that the printer is installed and online."
                )

            font = QFont("Courier New", 9)
            font.setStyleHint(QFont.StyleHint.Monospace)
            if self._raster_pt:                       # a fixed size chosen in the Receipt tab
                font.setPointSizeF(float(self._raster_pt))
            else:                                     # fit the columns, capped by the paper width
                fit_font_to_columns(font, painter, printer, self._columns,
                                    paper_width_mm=self._paper_width_mm)
            painter.setFont(font)

            fm        = painter.fontMetrics()
            line_h    = fm.height() + 1
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
            x         = int(page_rect.left()) + 10
            y_start   = int(page_rect.top())  + 10
            y_max     = int(page_rect.bottom()) - 10
            y         = y_start

            for line in text.split("\n"):
                painter.drawText(x, y + fm.ascent(), line)
                y += line_h
                if y + line_h > y_max:
                    printer.newPage()
                    y = y_start

            painter.end()

        except PrinterError:
            try: painter.end()
            except Exception: pass
            raise
        except Exception as e:
            try: painter.end()
            except Exception: pass
            raise PrinterError(str(e))
