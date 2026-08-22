"""
core/db_checkout.py
Checkout database — receipts, line items, void/refund/exchange records.

Tables
------
receipts      — one row per completed transaction
receipt_items — line items per receipt (snapshot of what was sold: name,
                barcode, price — doesn't change even if the product is later
                renamed or deleted in products.db)
refunds       — one row per void / full / partial refund / exchange action
                taken against a receipt
refund_items  — item-level detail for a refund action. Each row is tied to
                the exact receipt_items row it affects via receipt_item_id
                (a real, DB-enforced FK — receipt_items lives in this same
                file, unlike product_id/user_id elsewhere which cross files).

Reconciliation
--------------
Every refund_items row links to a specific receipt_items row and records
how many units of that line are being refunded. Before inserting, the
cumulative quantity already refunded against that line (across all past
refund actions) plus the new request is checked against the line's original
quantity — this is what prevents refunding the same units twice, which was
the core issue with the previous design (refund_items had no link back to
what was actually sold).

Soft (undeclared, cross-file) references — documented, not DB-enforced:
  receipts.user_id, receipts.session_id -> users.db
  receipt_items.product_id              -> products.db (NULL for misc/one-off items)
  refunds.user_id                       -> users.db
  refund_items.exchange_for_product_id  -> products.db
These rely on the UI only ever offering valid IDs (search/dropdown-driven
selection), per the agreed lightweight approach for cross-file references.
"""

import sqlite3
import threading
from contextlib import contextmanager
from config import DB_CHECKOUT

_local = threading.local()


@contextmanager
def _conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_CHECKOUT, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield _local.conn
    except Exception:
        _local.conn.rollback()
        raise


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_number  TEXT    NOT NULL UNIQUE,   -- e.g. "T01-0041"
    user_id         INTEGER NOT NULL,          -- cashier — soft ref, users.db
    session_id      INTEGER NOT NULL,          -- soft ref, users.db
    subtotal        REAL    NOT NULL DEFAULT 0.0,
    gct_amount      REAL    NOT NULL DEFAULT 0.0,
    discount_amount REAL    NOT NULL DEFAULT 0.0,
    total           REAL    NOT NULL DEFAULT 0.0,
    payment_method  TEXT    NOT NULL DEFAULT 'cash'
                            CHECK(payment_method IN ('cash','card','split')),
    cash_tendered   REAL    DEFAULT NULL,
    card_amount     REAL    DEFAULT NULL,
    change_given    REAL    DEFAULT NULL,
    status          TEXT    NOT NULL DEFAULT 'completed'
                            CHECK(status IN ('completed','voided','refunded')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    product_id      INTEGER,            -- soft ref, products.db — NULL for
                                         -- misc/one-off items with no product record
    barcode         TEXT    NOT NULL,
    product_name    TEXT    NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price      REAL    NOT NULL,
    discount_amount REAL    NOT NULL DEFAULT 0.0,
    gct_amount      REAL    NOT NULL DEFAULT 0.0,
    line_total      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL,   -- soft ref, users.db — who authorised it
    refund_type     TEXT    NOT NULL CHECK(refund_type IN ('void','partial','full','exchange')),
    reason          TEXT    NOT NULL DEFAULT '',
    amount          REAL    NOT NULL DEFAULT 0.0,  -- computed from refund_items, not caller-supplied
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS refund_items (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    refund_id                INTEGER NOT NULL REFERENCES refunds(id)       ON DELETE CASCADE,
    receipt_item_id          INTEGER NOT NULL REFERENCES receipt_items(id) ON DELETE CASCADE,
    quantity                 INTEGER NOT NULL CHECK(quantity > 0),
    line_amount              REAL    NOT NULL DEFAULT 0.0,  -- proportional line_total for this quantity
    -- Exchange-only: what it was swapped for (a NEW product, not on the
    -- original receipt, so no receipt_item_id available for this side)
    exchange_for_name        TEXT    DEFAULT NULL,
    exchange_for_product_id  INTEGER DEFAULT NULL  -- soft ref, products.db
);

CREATE INDEX IF NOT EXISTS idx_receipts_number     ON receipts(receipt_number);
CREATE INDEX IF NOT EXISTS idx_receipts_user       ON receipts(user_id);
CREATE INDEX IF NOT EXISTS idx_receipts_session    ON receipts(session_id);
CREATE INDEX IF NOT EXISTS idx_receipts_date       ON receipts(created_at);
CREATE INDEX IF NOT EXISTS idx_items_receipt       ON receipt_items(receipt_id);
CREATE INDEX IF NOT EXISTS idx_refunds_receipt     ON refunds(receipt_id);
CREATE INDEX IF NOT EXISTS idx_refund_items_refund ON refund_items(refund_id);
CREATE INDEX IF NOT EXISTS idx_refund_items_ritem  ON refund_items(receipt_item_id);
"""


def init_db():
    with _conn() as con:
        con.executescript(SCHEMA)
        con.commit()


# ── Receipt number generator ──────────────────────────────────────────────────

def _next_receipt_number(con) -> str:
    """Generate next receipt number using terminal ID prefix e.g. T01-0042."""
    try:
        from core.db_config import get as cfg_get
        tid = cfg_get("terminal_id", "T01").strip().upper() or "T01"
    except Exception:
        tid = "T01"

    prefix = f"{tid}-"
    row = con.execute(
        "SELECT receipt_number FROM receipts WHERE receipt_number LIKE ? "
        "ORDER BY id DESC LIMIT 1",
        (f"{prefix}%",)
    ).fetchone()

    if row:
        try:
            num = int(row["receipt_number"].split("-")[-1]) + 1
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1
    return f"{prefix}{num:04d}"


# ── Receipts ──────────────────────────────────────────────────────────────────

def save_receipt(
    user_id: int,
    session_id: int,
    items: list[dict],
    subtotal: float,
    gct_amount: float,
    discount_amount: float,
    total: float,
    payment_method: str = "cash",
    cash_tendered: float = None,
    card_amount: float = None,
    change_given: float = None,
) -> dict:
    """Persist a completed transaction. Returns the saved receipt dict
    including the auto-generated receipt_number.

    items dicts must contain:
        product_id, barcode, product_name, quantity,
        unit_price, discount_amount, gct_amount, line_total
    """
    with _conn() as con:
        receipt_number = _next_receipt_number(con)
        cur = con.execute(
            """INSERT INTO receipts
               (receipt_number, user_id, session_id, subtotal, gct_amount,
                discount_amount, total, payment_method,
                cash_tendered, card_amount, change_given)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (receipt_number, user_id, session_id, subtotal, gct_amount,
             discount_amount, total, payment_method,
             cash_tendered, card_amount, change_given)
        )
        receipt_id = cur.lastrowid
        con.executemany(
            """INSERT INTO receipt_items
               (receipt_id, product_id, barcode, product_name,
                quantity, unit_price, discount_amount, gct_amount, line_total)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(receipt_id,
              it["product_id"], it["barcode"], it["product_name"],
              it["quantity"], it["unit_price"], it["discount_amount"],
              it["gct_amount"], it["line_total"])
             for it in items]
        )
        con.commit()
        return get_receipt_by_id(receipt_id)


def get_receipt_by_id(receipt_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if not row:
            return None
        receipt = dict(row)
        receipt["items"] = [
            dict(r) for r in con.execute(
                "SELECT * FROM receipt_items WHERE receipt_id = ?", (receipt_id,)
            )
        ]
        return receipt


def get_receipt_by_number(receipt_number: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM receipts WHERE receipt_number = ?", (receipt_number,)
        ).fetchone()
        return get_receipt_by_id(row["id"]) if row else None


def count_receipts(
    user_id: int = None, session_id: int = None,
    status: str = None, search: str = "",
    date_from: str = "", date_to: str = "",
) -> int:
    q = "SELECT COUNT(*) FROM receipts WHERE 1=1"
    params: list = []
    if user_id    is not None: q += " AND user_id = ?";       params.append(user_id)
    if session_id is not None: q += " AND session_id = ?";    params.append(session_id)
    if status:                 q += " AND status = ?";        params.append(status)
    if search:
        q += " AND receipt_number LIKE ?";                    params.append(f"%{search}%")
    if date_from: q += " AND date(created_at) >= ?";         params.append(date_from)
    if date_to:   q += " AND date(created_at) <= ?";         params.append(date_to)
    with _conn() as con:
        return con.execute(q, params).fetchone()[0]


def get_receipts(
    user_id: int = None, session_id: int = None, status: str = None,
    search: str = "", date_from: str = "", date_to: str = "",
    limit: int = 200, offset: int = 0,
) -> list[dict]:
    q = "SELECT * FROM receipts WHERE 1=1"
    params: list = []
    if user_id    is not None: q += " AND user_id = ?";           params.append(user_id)
    if session_id is not None: q += " AND session_id = ?";        params.append(session_id)
    if status:                 q += " AND status = ?";            params.append(status)
    if search:
        q += " AND receipt_number LIKE ?"
        params.append(f"%{search}%")
    if date_from: q += " AND date(created_at) >= ?";             params.append(date_from)
    if date_to:   q += " AND date(created_at) <= ?";             params.append(date_to)
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_session_receipts(session_id: int) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM receipts WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,)
        )]


# ── Refund reconciliation core ──────────────────────────────────────────────

def get_remaining_refundable_qty(receipt_item_id: int) -> int:
    """Public helper for the UI: how many units of this receipt line are
    still eligible to be refunded (original quantity minus everything
    already refunded/voided/exchanged against it, across all past actions)."""
    with _conn() as con:
        ri = con.execute(
            "SELECT quantity FROM receipt_items WHERE id = ?", (receipt_item_id,)
        ).fetchone()
        if not ri:
            return 0
        return max(0, ri["quantity"] - get_refunded_quantity(con, receipt_item_id))

def get_refunded_quantity(con, receipt_item_id: int) -> int:
    """Total quantity already refunded against a specific receipt_items row,
    across all past void/refund/exchange actions."""
    row = con.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS q FROM refund_items WHERE receipt_item_id = ?",
        (receipt_item_id,)
    ).fetchone()
    return row["q"]


def _validate_and_price_items(con, requested: list[dict]) -> list[dict]:
    """Validate each {receipt_item_id, quantity, ...} request against what's
    actually left to refund on that line, and attach a computed line_amount
    (proportional share of the original line_total).

    Raises ValueError on any invalid request — over-refund, unknown
    receipt_item_id, or non-positive quantity — so the caller can surface
    a clear message instead of silently corrupting the totals.
    """
    priced = []
    for req in requested:
        ri = con.execute(
            "SELECT * FROM receipt_items WHERE id = ?", (req["receipt_item_id"],)
        ).fetchone()
        if not ri:
            raise ValueError(f"Receipt item {req['receipt_item_id']} not found.")

        qty = req["quantity"]
        if qty <= 0:
            raise ValueError(f"Refund quantity for {ri['product_name']} must be positive.")

        already = get_refunded_quantity(con, ri["id"])
        remaining = ri["quantity"] - already
        if qty > remaining:
            raise ValueError(
                f"Cannot refund {qty} of \"{ri['product_name']}\" — only "
                f"{remaining} of {ri['quantity']} remain unrefunded."
            )

        line_amount = round((ri["line_total"] / ri["quantity"]) * qty, 2)
        priced.append({
            "receipt_item_id": ri["id"],
            "quantity": qty,
            "line_amount": line_amount,
            "exchange_for_name": req.get("exchange_for_name"),
            "exchange_for_product_id": req.get("exchange_for_product_id"),
        })
    return priced


def _insert_refund(con, receipt_id: int, user_id: int, refund_type: str,
                   reason: str, priced_items: list[dict]) -> int:
    total = round(sum(it["line_amount"] for it in priced_items), 2)
    cur = con.execute(
        """INSERT INTO refunds (receipt_id, user_id, refund_type, reason, amount)
           VALUES (?,?,?,?,?)""",
        (receipt_id, user_id, refund_type, reason, total)
    )
    refund_id = cur.lastrowid
    con.executemany(
        """INSERT INTO refund_items
           (refund_id, receipt_item_id, quantity, line_amount,
            exchange_for_name, exchange_for_product_id)
           VALUES (?,?,?,?,?,?)""",
        [(refund_id, it["receipt_item_id"], it["quantity"], it["line_amount"],
          it["exchange_for_name"], it["exchange_for_product_id"])
         for it in priced_items]
    )
    return refund_id


# ── Void / Refund / Exchange ────────────────────────────────────────────────

def void_receipt(receipt_id: int, user_id: int, reason: str) -> bool:
    """Void a completed receipt. Automatically builds item-level refund_items
    for every line on the receipt (a void cancels the whole sale).

    Requests each line's REMAINING unrefunded quantity, not its original
    quantity — a receipt.status of 'completed' normally means nothing's
    been refunded yet, but this keeps void_receipt() safe to call even in
    an edge case where a line was already partially refunded first. Lines
    with nothing left to void are simply skipped rather than raising.
    """
    with _conn() as con:
        cur = con.execute(
            "UPDATE receipts SET status='voided' WHERE id=? AND status='completed'",
            (receipt_id,)
        )
        if cur.rowcount == 0:
            return False

        lines = con.execute(
            "SELECT id, quantity FROM receipt_items WHERE receipt_id = ?", (receipt_id,)
        ).fetchall()
        requested = []
        for r in lines:
            remaining = r["quantity"] - get_refunded_quantity(con, r["id"])
            if remaining > 0:
                requested.append({"receipt_item_id": r["id"], "quantity": remaining})

        if not requested:
            # Nothing left to void (everything already refunded) — still
            # mark the receipt voided since that update already committed
            # conceptually; just no new refund_items to add.
            con.commit()
            return True

        priced = _validate_and_price_items(con, requested)
        _insert_refund(con, receipt_id, user_id, "void", reason, priced)
        con.commit()
        return True


def refund_receipt(receipt_id: int, user_id: int, reason: str,
                   items: list[dict], refund_type: str = "partial") -> bool:
    """Refund some or all lines of a completed receipt.

    items — list of {receipt_item_id, quantity}. For a full refund, pass
    every line at its full quantity (or call with refund_type='full' and
    the same shape). The refund amount is computed from the items, not
    supplied by the caller.

    Raises ValueError (caught by caller / shown to user) if any requested
    quantity exceeds what's left unrefunded on that line.
    """
    if not items:
        return False
    with _conn() as con:
        row = con.execute(
            "SELECT id, status FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if not row or row["status"] not in ("completed", "refunded"):
            return False

        priced = _validate_and_price_items(con, items)
        _insert_refund(con, receipt_id, user_id, refund_type, reason, priced)

        # Mark fully refunded only when every line has nothing left
        remaining_total = con.execute(
            """SELECT COALESCE(SUM(ri.quantity), 0) AS total_qty
               FROM receipt_items ri WHERE ri.receipt_id = ?""",
            (receipt_id,)
        ).fetchone()["total_qty"]
        refunded_total = con.execute(
            """SELECT COALESCE(SUM(rfi.quantity), 0) AS refunded_qty
               FROM refund_items rfi
               JOIN receipt_items ri ON ri.id = rfi.receipt_item_id
               WHERE ri.receipt_id = ?""",
            (receipt_id,)
        ).fetchone()["refunded_qty"]
        if refunded_total >= remaining_total:
            con.execute("UPDATE receipts SET status='refunded' WHERE id=?", (receipt_id,))

        con.commit()
        return True


def exchange_receipt(receipt_id: int, user_id: int, reason: str,
                     items: list[dict]) -> bool:
    """Record an exchange against a completed receipt.

    items — list of {receipt_item_id, quantity, exchange_for_name,
                      exchange_for_product_id}
    """
    if not items:
        return False
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM receipts WHERE id=? AND status='completed'", (receipt_id,)
        ).fetchone()
        if not row:
            return False
        priced = _validate_and_price_items(con, items)
        _insert_refund(con, receipt_id, user_id, "exchange", reason, priced)
        con.commit()
        return True


def get_refund_items(refund_id: int) -> list[dict]:
    """Item-level detail for a refund, joined back to the original receipt line."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            """SELECT rfi.*, ri.product_name, ri.barcode, ri.unit_price AS original_unit_price,
                      ri.quantity AS original_quantity
               FROM refund_items rfi
               JOIN receipt_items ri ON ri.id = rfi.receipt_item_id
               WHERE rfi.refund_id = ? ORDER BY rfi.id""",
            (refund_id,)
        )]


def get_refunds_for_receipt(receipt_id: int) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM refunds WHERE receipt_id = ? ORDER BY id DESC",
            (receipt_id,)
        )]


def get_receipts_with_refund_summary(
    status: str = None, search: str = "",
    date_from: str = "", date_to: str = "",
    limit: int = 200, offset: int = 0,
) -> list[dict]:
    """Like get_receipts but enriches each row with refund summary data:
      - has_partial:    bool — has at least one partial refund
      - has_exchange:   bool — has at least one exchange record
      - refunded_total: float — sum of all partial refund amounts
    """
    receipts = get_receipts(
        status=status, search=search,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    if not receipts:
        return receipts
    ids = [r["id"] for r in receipts]
    placeholders = ",".join("?" * len(ids))
    with _conn() as con:
        rows = con.execute(
            f"""SELECT receipt_id,
                       SUM(CASE WHEN refund_type='partial' THEN amount ELSE 0 END) AS refunded_total,
                       MAX(CASE WHEN refund_type='partial' THEN 1 ELSE 0 END)      AS has_partial,
                       MAX(CASE WHEN refund_type='exchange' THEN 1 ELSE 0 END)     AS has_exchange
                FROM refunds
                WHERE receipt_id IN ({placeholders})
                GROUP BY receipt_id""",
            ids
        ).fetchall()
    summary = {r["receipt_id"]: dict(r) for r in rows}
    for rec in receipts:
        s = summary.get(rec["id"], {})
        rec["has_partial"]    = bool(s.get("has_partial", 0))
        rec["has_exchange"]   = bool(s.get("has_exchange", 0))
        rec["refunded_total"] = s.get("refunded_total", 0.0) or 0.0
    return receipts


def session_voided_receipts(session_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT r.receipt_number, r.total, r.created_at,
                      rf.reason, rf.created_at AS voided_at
               FROM receipts r
               LEFT JOIN refunds rf ON rf.receipt_id = r.id AND rf.refund_type = 'void'
               WHERE r.session_id = ? AND r.status = 'voided'
               ORDER BY r.created_at""",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Reporting helpers ─────────────────────────────────────────────────────────

def session_totals(session_id: int) -> dict:
    with _conn() as con:
        row = con.execute(
            """SELECT
                COUNT(*)                                        AS transaction_count,
                COALESCE(SUM(CASE WHEN status='completed'
                              THEN total ELSE 0 END), 0)       AS total_sales,
                COALESCE(SUM(CASE WHEN status='completed'
                              THEN gct_amount ELSE 0 END), 0)  AS total_gct,
                COALESCE(SUM(CASE WHEN status='completed'
                              THEN discount_amount ELSE 0 END),0) AS total_discount,
                COUNT(CASE WHEN status='voided'   THEN 1 END)  AS voided_count,
                COUNT(CASE WHEN status='refunded' THEN 1 END)  AS refunded_count
               FROM receipts WHERE session_id = ?""",
            (session_id,)
        ).fetchone()
        return dict(row)


def session_group_totals(session_id: int) -> list[dict]:
    """Sales broken down by product group for a session. Cross-file read via
    ATTACH — fine for querying, just not for FK enforcement."""
    from config import DB_PRODUCTS
    with _conn() as con:
        con.execute("ATTACH DATABASE ? AS pdb", (DB_PRODUCTS,))
        try:
            rows = con.execute(
                """SELECT
                       COALESCE(g.name, 'Ungrouped')  AS group_name,
                       SUM(ri.line_total)              AS total_sales,
                       SUM(ri.quantity)                AS item_count
                   FROM receipt_items ri
                   JOIN receipts r ON r.id = ri.receipt_id
                   LEFT JOIN pdb.products p ON p.id = ri.product_id
                   LEFT JOIN pdb.groups g ON g.id = p.group_id
                   WHERE r.session_id = ?
                     AND r.status = 'completed'
                   GROUP BY g.id, g.name
                   ORDER BY total_sales DESC""",
                (session_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.execute("DETACH DATABASE pdb")
