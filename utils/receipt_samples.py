"""Sample data for the designer's live preview and the test print."""
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
    """The unfinished lines for a sale / void / refund sample (the caller applies
    utils.receipt_layout.finalize_lines)."""
    from utils import receipt_formatter as rf
    r, b = sample_receipt(), sample_biz(biz)
    if kind == "void":
        return rf.format_void_lines(r, b, voided_by="SAMPLE SUPERVISOR",
                                    reason="Customer changed mind", currency=currency)
    if kind == "refund":
        return rf.format_refund_lines(r, b, refund_amount=500.0, refund_type="partial",
                                      refunded_by="SAMPLE SUPERVISOR", reason="Damaged item",
                                      currency=currency)
    return rf.format_sale_lines(r, b, currency)
