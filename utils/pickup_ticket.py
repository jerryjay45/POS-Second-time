"""
utils/pickup_ticket.py — second-printer "pickup ticket" for the serving station.

When enabled (Manager → Pickup tab), every completed sale also prints a short
ticket on a second printer: big order number, the items and quantities, no prices.
The cashier's own receipt is unchanged.

Settings live in config.db under pickup_* keys (per PC, like the receipt printer).
"""
from __future__ import annotations

import textwrap

Line = tuple[str, str]          # (text, kind) — same as utils.receipt_formatter

DEFAULTS: dict[str, str] = {
    "pickup_enabled":      "0",
    "pickup_printer_name": "",
    "pickup_copies":       "1",
    "pickup_escpos":       "1",
    "pickup_has_cutter":   "0",
    "pickup_columns":      "",     # "" = same width as the receipt printer
    "pickup_feed_lines":   "5",
    "pickup_title":        "PICKUP",
    "pickup_show_cashier": "0",
    "pickup_show_time":    "1",
    "pickup_bold_items":   "1",
}


def load_settings() -> dict[str, str]:
    """All pickup_* settings as strings, defaults filled in."""
    try:
        from core.db_config import get as cfg_get
        return {k: cfg_get(k, d) for k, d in DEFAULTS.items()}
    except Exception:
        return dict(DEFAULTS)


def is_active(s: dict[str, str] | None = None) -> bool:
    """On, and a printer is named. A blank name would fall back to the Windows default
    printer — usually the cashier's — so a blank name means 'do nothing'."""
    s = s or load_settings()
    return s["pickup_enabled"].strip() == "1" and bool(s["pickup_printer_name"].strip())


def _int(value: str, lo: int, hi: int, fallback: int) -> int:
    try:
        return min(hi, max(lo, int(str(value).strip())))
    except (TypeError, ValueError):
        return fallback


def order_number(receipt: dict) -> str:
    """'T01-0041' -> '0041' (the part the kitchen shouts out)."""
    return str(receipt.get("receipt_number", "")).replace("#", "").split("-")[-1].strip()


def _qty(q) -> str:
    try:
        f = float(q)
    except (TypeError, ValueError):
        return str(q)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _stamp(created_at: str) -> str:
    """'2026-11-16 14:03:22' -> '14:03' (falls back to the raw text)."""
    s = str(created_at or "")
    return s[11:16] if len(s) >= 16 and s[10] in " T" else s


def format_pickup_lines(receipt: dict, settings: dict[str, str], width: int) -> list[Line]:
    """Build the ticket. Kinds: 'biz_name' (centred, big — see build_escpos_bytes
    heading=), 'title' (bold), 'div', 'normal'. No prices anywhere."""
    w = max(16, width)
    div = ("-" * w, "div")
    bold = settings.get("pickup_bold_items", "1").strip() == "1"
    item_kind = "title" if bold else "normal"

    lines: list[Line] = []
    title = (settings.get("pickup_title") or "").strip()
    if title:
        lines.append((title.center(w).rstrip(), "title"))
    lines.append((order_number(receipt).center(w).rstrip(), "biz_name"))
    lines.append(div)
    if settings.get("pickup_show_time", "1").strip() == "1":
        lines.append((f"Time: {_stamp(receipt.get('created_at'))}", "normal"))
    if settings.get("pickup_show_cashier", "0").strip() == "1" and receipt.get("cashier_name"):
        lines.append((f"Cashier: {receipt['cashier_name']}", "normal"))
    if len(lines) > 3:
        lines.append(div)

    total_qty = 0.0
    for item in receipt.get("items", []):
        qty = item.get("quantity", 1)
        try:
            total_qty += float(qty)
        except (TypeError, ValueError):
            pass
        prefix = f"{_qty(qty)} x "
        wrapped = textwrap.wrap(str(item.get("product_name", "")), max(8, w - len(prefix)),
                                break_long_words=True) or [""]
        lines.append((prefix + wrapped[0], item_kind))
        lines += [(" " * len(prefix) + part, item_kind) for part in wrapped[1:]]
        note = str(item.get("note", "") or "").strip()      # future-proof: modifiers
        if note:
            lines.append((f"   * {note}", "normal"))

    lines.append(div)
    lines.append((f"Items: {_qty(total_qty)}", "normal"))
    return lines


def sample_receipt() -> dict:
    """Used by the Test print button."""
    return {
        "receipt_number": "T01-0042", "created_at": "2026-11-16 12:30:00",
        "cashier_name": "Test",
        "items": [
            {"product_name": "Chicken Combo", "quantity": 2},
            {"product_name": "Fries (large)", "quantity": 1},
            {"product_name": "Bottle of water with a deliberately long name to test wrapping",
             "quantity": 3},
        ],
    }
