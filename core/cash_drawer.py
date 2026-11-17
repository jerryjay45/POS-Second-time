"""
core/cash_drawer.py — expected cash, counted cash and variance for a session.

The rules live here (and nowhere in the UI) so the dashboard, the Z-report and the tests
all agree:

    expected = opening float + cash sales - cash refunds - paid-outs - safe drops
    variance = counted cash  - expected          (negative = the drawer is short)

Cash sales are what session_tender_summary() already reports (a split sale contributes only
its cash part), so this matches the Reports dashboard's Cash line. Change given back to the
customer is not subtracted: a sale's total is what stays in the drawer, not what was handed over.

A session with no recorded float (float_amount is NULL: tracking was off when it opened)
has no cash summary at all.
"""
from __future__ import annotations


def enabled() -> bool:
    from core.db_config import get_bool
    return get_bool("cash_drawer_enabled", False)


def standard_float() -> float:
    from core.db_config import get_float
    return max(0.0, get_float("cash_drawer_float", 0.0))


def compute_expected(float_amount: float, cash_sales: float, cash_refunds: float,
                     paid_outs: float = 0.0, safe_drops: float = 0.0) -> float:
    return round((float_amount or 0.0) + (cash_sales or 0.0) - (cash_refunds or 0.0)
                 - (paid_outs or 0.0) - (safe_drops or 0.0), 2)


def compute_variance(counted: float | None, expected: float) -> float | None:
    return None if counted is None else round(counted - expected, 2)


def session_cash_summary(session: dict | None) -> dict | None:
    """Everything the dashboard, the dialog and the Z-report show about a session's cash,
    or None when the session doesn't track a float."""
    if not session or session.get("float_amount") is None:
        return None
    from core.db_checkout import session_tender_summary, session_cash_refunds
    from core.db_users import get_user_by_id, paid_out_total, count_drawer_opens
    sales = round(session_tender_summary(session["id"])["cash"] or 0.0, 2)
    refunds = session_cash_refunds(session["id"])
    paid_outs  = paid_out_total(session["id"], "paid_out")
    safe_drops = paid_out_total(session["id"], "safe_drop")
    expected = compute_expected(session["float_amount"], sales, refunds, paid_outs, safe_drops)
    counted = session.get("counted_cash")
    counter = get_user_by_id(session["counted_by"]) if session.get("counted_by") else None
    return {
        "float":        round(session["float_amount"], 2),
        "cash_sales":   sales,
        "cash_refunds": refunds,
        "paid_outs":    paid_outs,
        "safe_drops":   safe_drops,
        "no_sale_opens": count_drawer_opens(session["id"]),
        "expected":     expected,
        "counted":      None if counted is None else round(counted, 2),
        "variance":     compute_variance(counted, expected),
        "counted_by":   counter["full_name"] if counter else "",
        "counted_at":   session.get("counted_at") or "",
        "is_open":      session.get("status") == "open",
        # closed and not yet counted -> the dashboard shows "Count pending"
        "pending":      session.get("status") == "closed" and counted is None,
    }
