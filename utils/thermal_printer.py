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


class ThermalPrinter:
    """
    Context manager — open/close handled automatically.

        with ThermalPrinter.from_config() as p:
            p.print_text(text)

    If printer_name is blank the OS default printer is used.
    """

    def __init__(self, printer_name: str = "", copies: int = 1,
                 mode: str = "raw"):
        self._name   = printer_name.strip()
        self._copies = max(1, copies)
        self._mode   = mode if mode in ("raw", "raster") else "raw"

    # ── Factory ───────────────────────────────────────────────────────

    @classmethod
    def from_config(cls) -> "ThermalPrinter":
        """Build from the settings DB."""
        try:
            from core.db_config import get as cfg_get
            name   = cfg_get("receipt_printer_name", "").strip()
            mode   = cfg_get("receipt_printer_mode", "raw").strip()
            copies = int(cfg_get("receipt_copies", "1") or "1")
        except Exception:
            name, mode, copies = "", "raw", 1
        return cls(name, copies, mode)

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
        raw   = (lines + "\n\f").encode("ascii", errors="replace")
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
