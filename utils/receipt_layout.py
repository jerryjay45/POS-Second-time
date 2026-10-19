"""
Receipt layout: the settings that shape a printed receipt, and the "finish"
pass applied to every receipt just before it is printed.

Two kinds of setting, kept apart on purpose:

  HARDWARE_DEFAULTS  belong to ONE printer on ONE PC (paper width, feed lines,
                     cutter, margin, queue name...). Never shared between
                     terminals — a TM-U220 and an 80 mm thermal need different
                     values.
  SHARED_DEFAULTS    the receipt's LOOK (which header lines show, footer text,
                     divider style). The same on every terminal of a business,
                     so these are the only settings a future terminal-to-terminal
                     sync needs to carry.

Every default reproduces the receipts the app printed before this module
existed, so nothing changes until someone edits a setting.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field

Line = tuple[str, str]          # (text, kind) — same as utils.receipt_formatter

# ── Settings ────────────────────────────────────────────────────────────────

HARDWARE_DEFAULTS: dict[str, str] = {
    "receipt_printer_name":          "",
    "receipt_printer_mode":          "raw",
    "receipt_paper_width_mm":        "76",
    "receipt_columns":               "",     # "" = work it out from the paper width
    "receipt_left_margin":           "0",    # blank columns on the left
    "receipt_feed_lines":            "",     # "" = legacy: leave the formatter's 2 blank lines
    "receipt_form_feed":             "1",    # plain-text raw jobs end with a form feed
    "receipt_printer_escpos":        "0",
    "receipt_printer_has_cutter":    "1",
    "cash_drawer_kick_on_cash_sale": "0",
    "receipt_copies":                "1",
}

SHARED_DEFAULTS: dict[str, str] = {
    "receipt_show_address": "1",
    "receipt_show_phone":   "1",
    "receipt_show_trn":     "1",
    "receipt_show_cashier": "1",
    "receipt_header_extra": "",     # extra centred lines under the business details
    "receipt_footer_extra": "",     # extra centred lines under the footer message
    "receipt_divider":      "-",
}

DIVIDER_CHOICES = ["-", "=", "*", "_", ".", "~"]

# key -> validation rule. ("int", lo, hi) | ("optint", lo, hi) | ("bool",)
#       | ("choice", [...]) | ("text", max_chars) | ("lines", max_lines, max_chars)
SPEC: dict[str, tuple] = {
    "receipt_printer_name":          ("text", 200),
    "receipt_printer_mode":          ("choice", ["raw", "raster"]),
    "receipt_paper_width_mm":        ("int", 30, 120),
    "receipt_columns":               ("optint", 16, 80),
    "receipt_left_margin":           ("int", 0, 10),
    "receipt_feed_lines":            ("optint", 0, 20),
    "receipt_form_feed":             ("bool",),
    "receipt_printer_escpos":        ("bool",),
    "receipt_printer_has_cutter":    ("bool",),
    "cash_drawer_kick_on_cash_sale": ("bool",),
    "receipt_copies":                ("int", 1, 5),
    "receipt_show_address":          ("bool",),
    "receipt_show_phone":            ("bool",),
    "receipt_show_trn":              ("bool",),
    "receipt_show_cashier":          ("bool",),
    "receipt_header_extra":          ("lines", 4, 60),
    "receipt_footer_extra":          ("lines", 4, 60),
    "receipt_divider":               ("choice", DIVIDER_CHOICES),
}


def validate_value(key: str, value) -> tuple[bool, str, str]:
    """Check one setting. Returns (ok, normalised_value, error_message)."""
    rule = SPEC.get(key)
    if rule is None:
        return False, "", "unknown setting"
    v = "" if value is None else str(value)
    kind = rule[0]
    if kind in ("int", "optint"):
        if kind == "optint" and v.strip() == "":
            return True, "", ""
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            return False, "", f"'{v}' is not a number"
        if not rule[1] <= n <= rule[2]:
            return False, "", f"{n} is outside the allowed range {rule[1]}–{rule[2]}"
        return True, str(n), ""
    if kind == "bool":
        if v.strip().lower() in ("1", "true", "yes", "on"):
            return True, "1", ""
        if v.strip().lower() in ("0", "false", "no", "off", ""):
            return True, "0", ""
        return False, "", f"'{v}' is not on/off"
    if kind == "choice":
        if v in rule[1]:
            return True, v, ""
        return False, "", f"'{v}' is not one of {', '.join(rule[1])}"
    if kind == "text":
        v = v.strip()
        if len(v) > rule[1]:
            return False, "", f"longer than {rule[1]} characters"
        return True, v, ""
    if kind == "lines":
        rows = [r.rstrip() for r in v.replace("\r", "").split("\n")]
        while rows and rows[-1] == "":
            rows.pop()
        if len(rows) > rule[1]:
            return False, "", f"more than {rule[1]} lines"
        if any(len(r) > rule[2] for r in rows):
            return False, "", f"a line is longer than {rule[2]} characters"
        return True, "\n".join(rows), ""
    return False, "", "unsupported rule"


# ── Loaded layout ───────────────────────────────────────────────────────────

@dataclass
class Layout:
    columns: int = 40                 # physical columns on the paper
    margin: int = 0                   # blank columns on the left
    feed_lines: int | None = None     # None = legacy (keep the formatter's 2 blank lines)
    form_feed: bool = True
    divider: str = "-"
    show_address: bool = True
    show_phone: bool = True
    show_trn: bool = True
    show_cashier: bool = True
    header_extra: list[str] = field(default_factory=list)
    footer_extra: list[str] = field(default_factory=list)

    @property
    def width(self) -> int:
        """Columns available to the receipt text (paper columns minus margin)."""
        return max(16, self.columns - self.margin)


def _get(key: str) -> str:
    default = HARDWARE_DEFAULTS.get(key, SHARED_DEFAULTS.get(key, ""))
    try:
        from core.db_config import get as cfg_get
        return cfg_get(key, default)
    except Exception:
        return default


def _int(key: str, fallback: int) -> int:
    ok, v, _ = validate_value(key, _get(key))
    return int(v) if ok and v != "" else fallback


def columns_from_settings(width_mm: str, override: str) -> int:
    from utils.printer_capabilities import columns_for_width_mm, FALLBACK_COLUMNS
    ok, v, _ = validate_value("receipt_columns", override)
    if ok and v != "":
        return int(v)
    try:
        return columns_for_width_mm(width_mm) if str(width_mm).strip() else FALLBACK_COLUMNS
    except Exception:
        return FALLBACK_COLUMNS


def layout_from_values(values: dict[str, str]) -> Layout:
    """Build a Layout from a settings dict (saved settings, or unsaved ones from the
    designer's controls). Missing keys use the defaults."""
    def g(k: str) -> str:
        return str(values.get(k, HARDWARE_DEFAULTS.get(k, SHARED_DEFAULTS.get(k, ""))))
    cols = columns_from_settings(g("receipt_paper_width_mm"), g("receipt_columns"))
    ok_m, m, _ = validate_value("receipt_left_margin", g("receipt_left_margin"))
    margin = min(int(m) if ok_m and m != "" else 0, max(0, cols - 16))
    ok, feed, _ = validate_value("receipt_feed_lines", g("receipt_feed_lines"))
    div = g("receipt_divider")
    return Layout(
        columns=cols,
        margin=margin,
        feed_lines=int(feed) if ok and feed != "" else None,
        form_feed=g("receipt_form_feed").strip() != "0",
        divider=div if div in DIVIDER_CHOICES else "-",
        show_address=g("receipt_show_address") != "0",
        show_phone=g("receipt_show_phone") != "0",
        show_trn=g("receipt_show_trn") != "0",
        show_cashier=g("receipt_show_cashier") != "0",
        # empty text = NO extra lines (not one blank line)
        header_extra=g("receipt_header_extra").split("\n") if g("receipt_header_extra").strip() else [],
        footer_extra=g("receipt_footer_extra").split("\n") if g("receipt_footer_extra").strip() else [],
    )


def fold_target_from_values(values: dict[str, str]) -> str | None:
    if str(values.get("receipt_printer_mode", "raw")).strip() == "raster":
        return None
    if str(values.get("receipt_printer_escpos", "0")).strip() == "1":
        return "cp437"
    return "ascii"


# A preview can render with UNSAVED settings: inside `use_layout(...)` the
# formatter and finalize_lines see these values instead of the saved ones.
_override_layout: Layout | None = None
_override_fold: object = None          # _UNSET-like sentinel handled below
_override_active = False


class use_layout:
    def __init__(self, values: dict[str, str]):
        self._layout = layout_from_values(values)
        self._fold = fold_target_from_values(values)

    def __enter__(self):
        global _override_layout, _override_fold, _override_active
        self._prev = (_override_layout, _override_fold, _override_active)
        _override_layout, _override_fold, _override_active = self._layout, self._fold, True
        return self._layout

    def __exit__(self, *exc):
        global _override_layout, _override_fold, _override_active
        _override_layout, _override_fold, _override_active = self._prev


def load_layout() -> Layout:
    if _override_active and _override_layout is not None:
        return _override_layout
    return layout_from_values({k: _get(k) for k in SPEC})


# ── Text folding (non-ASCII characters on printers that can't print them) ───

_FOLD = {
    "\u2014": "-", "\u2013": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
    "\u00d7": "x", "\u2715": "x", "\u2018": "'", "\u2019": "'", "\u201c": '"',
    "\u201d": '"', "\u2026": "...", "\u2264": "<=", "\u2265": ">=", "\u2022": "*",
    "\u00b7": ".", "\u20ac": "EUR", "\u00a3": "GBP", "\u00a0": " ", "\u2192": "->",
    "\u2713": "v", "\u2714": "v", "\u26a0": "!", "\u00ae": "(R)", "\u2122": "(TM)",
}


def _fold_char(ch: str, target: str) -> str:
    if ord(ch) < 128:
        return ch
    if target == "cp437":
        try:
            ch.encode("cp437")
            return ch                     # the printer can print this one natively
        except UnicodeEncodeError:
            pass
    if ch in _FOLD:
        return _FOLD[ch]
    base = unicodedata.normalize("NFKD", ch)
    base = "".join(c for c in base if not unicodedata.combining(c))
    if base and all(ord(c) < 128 for c in base):
        return base
    return "?"


def fold_text(text: str, target: str | None) -> str:
    """target: 'ascii' (plain-text raw), 'cp437' (ESC/POS raw), None (leave alone)."""
    if target is None or text.isascii():
        return text
    return "".join(_fold_char(c, target) for c in text)


def fold_target() -> str | None:
    """Which character set the CURRENT print mode can actually print."""
    if _override_active:
        return _override_fold
    if _get("receipt_printer_mode").strip() == "raster":
        return None                       # Qt draws any character the font has
    if _get("receipt_printer_escpos").strip() == "1":
        return "cp437"
    return "ascii"


# ── The finish pass ─────────────────────────────────────────────────────────

_UNSET = object()


def finalize_lines(lines: list[Line], layout: Layout | None = None, *,
                   feed_override=_UNSET, margin_override=_UNSET,
                   fold=_UNSET) -> list[Line]:
    """Apply the layout to a finished receipt: character folding, divider
    style, left margin and the number of blank lines fed after it.

    feed_override / margin_override / fold let a caller (the calibration
    sheets, the preview) ignore the saved setting for one print."""
    lay = layout or load_layout()
    feed   = lay.feed_lines if feed_override is _UNSET else feed_override
    margin = lay.margin     if margin_override is _UNSET else margin_override
    target = fold_target()  if fold is _UNSET else fold
    pad = " " * max(0, margin or 0)

    out: list[Line] = []
    for text, kind in lines:
        text = fold_text(text, target)
        if kind == "div" and text and set(text) == {"-"} and lay.divider != "-":
            text = lay.divider * len(text)
        if pad and text.strip():
            text = pad + text
        out.append((text, kind))

    if feed is not None:                              # explicit feed setting
        while out and not out[-1][0].strip():
            out.pop()
        out.extend([("", "normal")] * int(feed))
    return out


# ── Setup code (so two PCs can be compared at a glance) ─────────────────────

def setup_code(values: dict[str, str]) -> str:
    """Short fingerprint of the layout + printer settings (not the queue name)."""
    keys = sorted(k for k in SPEC if k != "receipt_printer_name")
    canon = {k: validate_value(k, values.get(k, HARDWARE_DEFAULTS.get(k, SHARED_DEFAULTS.get(k, ""))))[1]
             for k in keys}
    digest = hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest().upper()
    return f"{digest[:4]}-{digest[4:8]}"
