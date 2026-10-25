"""Sample data for the designer's live preview and the test print.

Kinds: sale, void, refund, and the three session reports (report_full, report_products,
report_summary) - REPORT_KINDS."""
from __future__ import annotations


def sample_receipt() -> dict:
    return {
        "id": 0, "user_id": None, "receipt_number": "01-0001",
        "created_at": "2026-10-16 10:30:00", "payment_method": "cash",
        "cashier_name": "SAMPLE CASHIER", "status": "completed",
        "subtotal": 4300.0, "gct_amount": 0.0, "discount_amount": 100.0, "total": 4200.0,
        "cash_tendered": 5000.0, "change_given": 800.0, "card_amount": None,
        "items": [
            {"id": 1, "product_name": "JUICE BOX 200ML", "quantity": 2, "unit_price": 250.0,
             "line_total": 500.0, "discount_amount": 0.0, "gct_amount": 0.0, "product_id": 1},
            {"id": 2, "product_name": "POST HONEY BUNCHES OF OATS W/CINNAMON 14.5 OZ",
             "quantity": 1, "unit_price": 2000.0, "line_total": 2000.0,
             "discount_amount": 100.0, "gct_amount": 0.0, "product_id": 2},
            {"id": 3, "product_name": "BREAD", "quantity": 3, "unit_price": 600.0,
             "line_total": 1800.0, "discount_amount": 0.0, "gct_amount": 0.0, "product_id": 3},
        ],
    }


REPORT_KINDS = ("report_full", "report_products", "report_summary")

# product -> sales group, for the sample "SALES BY GROUP" section
_GROUPS = {"JUICE BOX 200ML": "BEVERAGES", "BREAD": "BAKERY", "RICE 2LB": "GROCERY",
           "POST HONEY BUNCHES OF OATS W/CINNAMON 14.5 OZ": "GROCERY",
           "DISH SOAP 500ML": "HOUSEHOLD"}


def _sample_items(rows: list[tuple]) -> list[dict]:
    """rows: (name, qty, unit_price[, gct_amount]) -> receipt item dicts."""
    out = []
    for i, row in enumerate(rows, 1):
        name, qty, price = row[0], row[1], row[2]
        gct = row[3] if len(row) > 3 else 0.0
        out.append({"id": i, "product_name": name, "quantity": qty, "unit_price": price,
                    "line_total": qty * price, "discount_amount": 0.0,
                    "gct_amount": gct, "product_id": i})
    return out


def sample_session_receipts() -> list[dict]:
    """Three completed sales (the first is the same sample as the sale preview)."""
    r1 = sample_receipt()
    out = [r1]
    for num, when, method, rows in (
        ("01-0002", "2026-10-16 11:05:00", "card",
         [("JUICE BOX 200ML", 1, 250.0), ("BREAD", 2, 600.0)]),
        ("01-0003", "2026-10-16 14:20:00", "cash",
         [("BREAD", 1, 600.0), ("RICE 2LB", 2, 380.0), ("DISH SOAP 500ML", 1, 450.0, 58.70)]),
    ):
        items = _sample_items(rows)
        total = sum(i["line_total"] for i in items)
        out.append({"id": 0, "user_id": None, "receipt_number": num, "created_at": when,
                    "payment_method": method, "cashier_name": "SAMPLE CASHIER",
                    "status": "completed", "subtotal": total, "gct_amount": sum(i["gct_amount"] for i in items),
                    "discount_amount": 0.0, "total": total, "cash_tendered": None,
                    "change_given": None, "card_amount": None, "items": items})
    return out


def sample_session() -> dict:
    return {"id": 12, "user_id": None, "status": "closed",
            "opened_at": "2026-10-16 08:00:00", "closed_at": "2026-10-16 16:45:00"}


def sample_session_voided() -> list[dict]:
    return [{"receipt_number": "01-0004", "created_at": "2026-10-16 15:10:00",
             "total": 750.0, "reason": "Customer changed mind"}]


def sample_session_totals(receipts: list[dict], voided: list[dict]) -> dict:
    return {"transaction_count": len(receipts) + len(voided), "voided_count": len(voided),
            "refunded_count": 0,
            "total_sales": sum(r["total"] for r in receipts),
            "total_gct": sum(r["gct_amount"] for r in receipts),
            "total_discount": sum(r["discount_amount"] for r in receipts)}


def sample_group_totals(receipts: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in receipts:
        for it in r["items"]:
            g = groups.setdefault(_GROUPS.get(it["product_name"], "OTHER"),
                                  {"group_name": _GROUPS.get(it["product_name"], "OTHER"),
                                   "item_count": 0, "total_sales": 0.0})
            g["item_count"] += it["quantity"]
            g["total_sales"] += it["line_total"]
    return sorted(groups.values(), key=lambda g: g["total_sales"], reverse=True)


def sample_biz(real: dict | None = None) -> dict:
    """The real business details when they are filled in, otherwise a stand-in."""
    real = real or {}
    fallback = {"name": "MY STORE", "address": "1 MAIN STREET, PORTMORE",
                "phone": "876-555-0100", "tax_id": "123-456-789",
                "receipt_footer": "Thank you for your business!"}
    out = dict(fallback)
    for k, v in real.items():
        if v and k in fallback and not (k == "name" and v == "My Business"):
            out[k] = v
    return out


def preview_lines(kind: str, biz: dict | None = None, currency: str = "$"):
    """The unfinished lines for a sale / void / refund / session-report sample (the
    caller applies utils.receipt_layout.finalize_lines). The reports are built by the
    real format_session_lines, so they follow the saved/unsaved layout like a real print."""
    from utils import receipt_formatter as rf
    r, b = sample_receipt(), sample_biz(biz)
    if kind in REPORT_KINDS:
        rtype = kind.split("_", 1)[1]                    # full | products | summary
        receipts, voided = sample_session_receipts(), sample_session_voided()
        return rf.format_session_lines(
            sample_session(), sample_session_totals(receipts, voided), "SAMPLE CASHIER", b,
            opened_by="SAMPLE SUPERVISOR", closed_by="SAMPLE SUPERVISOR", currency=currency,
            report_type=rtype, group_totals=sample_group_totals(receipts),
            voided_receipts=voided,
            all_receipts=receipts if rtype in ("full", "products") else None)
    if kind == "void":
        return rf.format_void_lines(r, b, voided_by="SAMPLE SUPERVISOR",
                                    reason="Customer changed mind", currency=currency)
    if kind == "refund":
        return rf.format_refund_lines(r, b, refund_amount=500.0, refund_type="partial",
                                      refunded_by="SAMPLE SUPERVISOR", reason="Damaged item",
                                      currency=currency)
    return rf.format_sale_lines(r, b, currency)
