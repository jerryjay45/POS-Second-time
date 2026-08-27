"""
core/db_products.py
Products database — redesigned schema.

Tables
------
groups            — margin-based product grouping
discount_levels   — shared, reusable discount tiers (min qty -> percent)
alias_groups      — same-priced products under different barcodes.
                     Shares cost / selling_price / discounts ONLY.
                     Members keep their own name, barcode, and stock.
variant_groups    — true variants of one product (size/flavor/etc).
                     Shares cost / selling_price / discounts / STOCK.
                     Members keep their own name and barcode; stock is
                     tracked on the group, not the member.
products          — main product records. A product is at most ONE of:
                     standalone, alias-group member, variant-group member,
                     or a case product (is_case = 1). Case products link
                     to what they are a case OF via case_product_id
                     (a standalone single) or case_variant_group_id
                     (a variant group) — never both.
stock_adjustments — audit trail for manual stock changes, unified across
                     standalone products and variant groups.

Design notes
------------
- alias_groups and variant_groups are deliberately separate tables
  (not one generic "price_groups" with a type flag) so each one's
  columns match exactly what it needs — variant_groups has `stock`,
  alias_groups does not.
- Cost/price cascades are two hops deep in one case: an alias_group's
  cost change must reach not just its member products but also any
  case product whose case_product_id points at one of those members.
  See cascade_alias_group_to_cases().
"""

import sqlite3
import threading
from contextlib import contextmanager
from config import DB_PRODUCTS

_local = threading.local()


@contextmanager
def _conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PRODUCTS, check_same_thread=False)
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
CREATE TABLE IF NOT EXISTS groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    profit_margin REAL    NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS discount_levels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    min_qty     INTEGER NOT NULL DEFAULT 1,
    percent     REAL    NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS alias_groups (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT    NOT NULL UNIQUE,  -- internal label only, not a product name
    cost                  REAL    NOT NULL DEFAULT 0.0,
    selling_price         REAL    NOT NULL DEFAULT 0.0,
    discount_level1_id    INTEGER REFERENCES discount_levels(id) ON DELETE SET NULL,
    discount_level2_id    INTEGER REFERENCES discount_levels(id) ON DELETE SET NULL,
    inline_discount1_qty  INTEGER DEFAULT NULL,
    inline_discount1_pct  REAL    DEFAULT NULL,
    inline_discount2_qty  INTEGER DEFAULT NULL,
    inline_discount2_pct  REAL    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS variant_groups (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT    NOT NULL UNIQUE,
    cost                  REAL    NOT NULL DEFAULT 0.0,
    selling_price         REAL    NOT NULL DEFAULT 0.0,
    stock                 INTEGER NOT NULL DEFAULT 0,
    discount_level1_id    INTEGER REFERENCES discount_levels(id) ON DELETE SET NULL,
    discount_level2_id    INTEGER REFERENCES discount_levels(id) ON DELETE SET NULL,
    inline_discount1_qty  INTEGER DEFAULT NULL,
    inline_discount1_pct  REAL    DEFAULT NULL,
    inline_discount2_qty  INTEGER DEFAULT NULL,
    inline_discount2_pct  REAL    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode           TEXT    NOT NULL UNIQUE,
    name              TEXT    NOT NULL,
    group_id          INTEGER REFERENCES groups(id) ON DELETE SET NULL,

    -- Own pricing/stock — authoritative only when standalone
    -- (alias_group_id IS NULL AND variant_group_id IS NULL)
    cost              REAL    NOT NULL DEFAULT 0.0,
    selling_price     REAL    NOT NULL DEFAULT 0.0,
    stock             INTEGER NOT NULL DEFAULT 0,

    -- Membership — mutually exclusive with each other and with is_case
    alias_group_id    INTEGER REFERENCES alias_groups(id)   ON DELETE SET NULL,
    variant_group_id  INTEGER REFERENCES variant_groups(id) ON DELETE SET NULL,

    -- Own discounts — authoritative only when standalone
    discount_level1_id    INTEGER REFERENCES discount_levels(id) ON DELETE SET NULL,
    discount_level2_id    INTEGER REFERENCES discount_levels(id) ON DELETE SET NULL,
    inline_discount1_qty  INTEGER DEFAULT NULL,
    inline_discount1_pct  REAL    DEFAULT NULL,
    inline_discount2_qty  INTEGER DEFAULT NULL,
    inline_discount2_pct  REAL    DEFAULT NULL,

    gct_applicable    INTEGER NOT NULL DEFAULT 1,

    -- Case product flag + link to what it's a case OF
    is_case                INTEGER NOT NULL DEFAULT 0,
    case_qty               INTEGER DEFAULT NULL,
    case_product_id        INTEGER REFERENCES products(id)       ON DELETE SET NULL,
    case_variant_group_id  INTEGER REFERENCES variant_groups(id) ON DELETE SET NULL,

    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- A product is at most one of: alias-group member, variant-group member, case product
    CHECK (
        (CASE WHEN alias_group_id   IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN variant_group_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN is_case = 1                  THEN 1 ELSE 0 END) <= 1
    ),
    -- A case product is a case of a single product OR a variant group, never both
    CHECK (case_product_id IS NULL OR case_variant_group_id IS NULL)
);

CREATE TABLE IF NOT EXISTS stock_adjustments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id        INTEGER REFERENCES products(id) ON DELETE CASCADE,
    variant_group_id  INTEGER REFERENCES variant_groups(id) ON DELETE CASCADE,
    qty_change        INTEGER NOT NULL,
    reason            TEXT    NOT NULL DEFAULT 'Restock',
    adjusted_by       INTEGER DEFAULT NULL,
    adjusted_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK ((product_id IS NULL) != (variant_group_id IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_products_barcode      ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_name         ON products(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_products_alias_grp    ON products(alias_group_id);
CREATE INDEX IF NOT EXISTS idx_products_variant_grp  ON products(variant_group_id);
CREATE INDEX IF NOT EXISTS idx_products_case_product ON products(case_product_id);
CREATE INDEX IF NOT EXISTS idx_products_case_vg      ON products(case_variant_group_id);
CREATE INDEX IF NOT EXISTS idx_stock_adj_product     ON stock_adjustments(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_adj_variant     ON stock_adjustments(variant_group_id);
"""


def init_db():
    """Create all tables (idempotent)."""
    with _conn() as con:
        con.executescript(SCHEMA)
        con.commit()


# ── Groups (margin) ─────────────────────────────────────────────────────────

def get_groups() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute("SELECT * FROM groups ORDER BY name")]


def add_group(name: str) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO groups (name) VALUES (?)", (name.strip().upper(),)
        )
        con.commit()
        return cur.lastrowid


def update_group_margin(group_id: int, profit_margin: float):
    with _conn() as con:
        con.execute(
            "UPDATE groups SET profit_margin = ? WHERE id = ?",
            (profit_margin, group_id)
        )
        con.commit()


def delete_group(group_id: int):
    with _conn() as con:
        con.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        con.commit()


def recalculate_selling_prices(group_id: int = None) -> int:
    """Recalculate selling_price = cost * (1 + profit_margin) for standalone
    products in the given group (or all groups). Skips alias/variant members
    since their price lives on the group, not the product row."""
    with _conn() as con:
        q = """SELECT p.id, p.cost, g.profit_margin
               FROM products p JOIN groups g ON g.id = p.group_id
               WHERE p.alias_group_id IS NULL AND p.variant_group_id IS NULL
                 AND p.is_case = 0"""
        params = []
        if group_id is not None:
            q += " AND p.group_id = ?"
            params.append(group_id)
        rows = con.execute(q, params).fetchall()
        updated = 0
        for r in rows:
            new_price = round(r["cost"] * (1 + r["profit_margin"]), 2)
            con.execute(
                "UPDATE products SET selling_price = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (new_price, r["id"])
            )
            updated += 1
        con.commit()
        return updated


# ── Discount levels ──────────────────────────────────────────────────────────

def get_discount_levels() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM discount_levels ORDER BY min_qty"
        )]


def add_discount_level(name: str, min_qty: int, percent: float) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO discount_levels (name, min_qty, percent) VALUES (?, ?, ?)",
            (name.strip(), min_qty, percent)
        )
        con.commit()
        return cur.lastrowid


def update_discount_level(level_id: int, name: str = None,
                          min_qty: int = None, percent: float = None):
    sets, params = [], []
    if name is not None:
        sets.append("name = ?"); params.append(name.strip())
    if min_qty is not None:
        sets.append("min_qty = ?"); params.append(min_qty)
    if percent is not None:
        sets.append("percent = ?"); params.append(percent)
    if not sets:
        return
    params.append(level_id)
    with _conn() as con:
        con.execute(f"UPDATE discount_levels SET {', '.join(sets)} WHERE id = ?", params)
        con.commit()


def delete_discount_level(level_id: int):
    with _conn() as con:
        con.execute("DELETE FROM discount_levels WHERE id = ?", (level_id,))
        con.commit()


# ── Alias groups (shared cost/price/discount — NOT stock or name) ──────────

def get_alias_groups() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute("SELECT * FROM alias_groups ORDER BY name")]


def get_alias_group_by_id(group_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM alias_groups WHERE id = ?", (group_id,)).fetchone()
        return dict(row) if row else None


def add_alias_group(name: str, cost: float = 0.0, selling_price: float = 0.0,
                    discount_level1_id: int = None, discount_level2_id: int = None) -> int:
    clean = name.strip().upper()
    with _conn() as con:
        existing = con.execute(
            "SELECT id FROM alias_groups WHERE name = ?", (clean,)
        ).fetchone()
        if existing:
            raise ValueError(f'An alias group named "{clean}" already exists.')
        cur = con.execute(
            """INSERT INTO alias_groups (name, cost, selling_price,
                                          discount_level1_id, discount_level2_id)
               VALUES (?, ?, ?, ?, ?)""",
            (clean, cost, selling_price, discount_level1_id, discount_level2_id)
        )
        con.commit()
        return cur.lastrowid


def update_alias_group(group_id: int, **fields) -> list[dict]:
    """Update an alias group and cascade cost/price to members AND any case
    products linked off those members. Returns list of all affected product dicts.

    Only cost/selling_price changes need to cascade — discounts are read live
    via the FK at sale time, nothing to propagate.
    """
    if not fields:
        return []
    if "name" in fields:
        fields["name"] = fields["name"].strip().upper()
    sets = [f"{k} = ?" for k in fields]
    params = list(fields.values()) + [group_id]
    with _conn() as con:
        con.execute(f"UPDATE alias_groups SET {', '.join(sets)} WHERE id = ?", params)

        affected = []
        if "cost" in fields or "selling_price" in fields:
            affected = cascade_alias_group_to_cases(con, group_id)
        con.commit()
        return affected


def cascade_alias_group_to_cases(con, alias_group_id: int) -> list[dict]:
    """After an alias group's cost changes, recompute cost/selling_price for
    any case product whose case_product_id points at a member of that group.

    Two-hop cascade: alias_group -> member products -> cases of those members.
    Must be called with cost/selling_price already updated on alias_groups.
    """
    from core.db_config import get as cfg_get
    try:
        case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
    except (ValueError, TypeError):
        case_profit_pct = 0.10

    group = con.execute("SELECT cost FROM alias_groups WHERE id = ?", (alias_group_id,)).fetchone()
    if not group or group["cost"] <= 0:
        return []

    members = con.execute(
        "SELECT id FROM products WHERE alias_group_id = ?", (alias_group_id,)
    ).fetchall()

    affected = []
    for m in members:
        cases = con.execute(
            "SELECT id, case_qty, name FROM products WHERE is_case = 1 AND case_product_id = ?",
            (m["id"],)
        ).fetchall()
        for c in cases:
            qty = c["case_qty"] or 1
            case_cost = round(group["cost"] * qty, 4)
            case_price = round(case_cost * (1 + case_profit_pct), 2)
            con.execute(
                """UPDATE products SET cost = ?, selling_price = ?, updated_at = datetime('now', 'localtime')
                   WHERE id = ?""",
                (case_cost, case_price, c["id"])
            )
            affected.append({"id": c["id"], "name": c["name"]})
    return affected


def delete_alias_group(group_id: int):
    """Delete an alias group. Member products fall back to standalone
    (alias_group_id set NULL via FK) — their own cost/price/discount
    columns become authoritative again and should be reviewed."""
    with _conn() as con:
        con.execute("DELETE FROM alias_groups WHERE id = ?", (group_id,))
        con.commit()


# ── Variant groups (shared cost/price/discount/STOCK) ───────────────────────

def get_variant_groups() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute("SELECT * FROM variant_groups ORDER BY name")]


def get_variant_group_by_id(group_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM variant_groups WHERE id = ?", (group_id,)).fetchone()
        return dict(row) if row else None


def add_variant_group(name: str, cost: float = 0.0, selling_price: float = 0.0,
                      stock: int = 0,
                      discount_level1_id: int = None, discount_level2_id: int = None) -> int:
    clean = name.strip().upper()
    with _conn() as con:
        existing = con.execute(
            "SELECT id FROM variant_groups WHERE name = ?", (clean,)
        ).fetchone()
        if existing:
            raise ValueError(f'A variant group named "{clean}" already exists.')
        cur = con.execute(
            """INSERT INTO variant_groups (name, cost, selling_price, stock,
                                            discount_level1_id, discount_level2_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (clean, cost, selling_price, stock, discount_level1_id, discount_level2_id)
        )
        con.commit()
        return cur.lastrowid


def update_variant_group(group_id: int, **fields) -> list[dict]:
    """Update a variant group and cascade cost/price to any case products
    linked via case_variant_group_id. Returns affected case product dicts.
    Stock lives only on the group — nothing to cascade for stock changes."""
    if not fields:
        return []
    if "name" in fields:
        fields["name"] = fields["name"].strip().upper()
    sets = [f"{k} = ?" for k in fields]
    params = list(fields.values()) + [group_id]
    with _conn() as con:
        con.execute(f"UPDATE variant_groups SET {', '.join(sets)} WHERE id = ?", params)

        affected = []
        if "cost" in fields:
            affected = cascade_variant_group_to_cases(con, group_id)
        con.commit()
        return affected


def cascade_variant_group_to_cases(con, variant_group_id: int) -> list[dict]:
    from core.db_config import get as cfg_get
    try:
        case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
    except (ValueError, TypeError):
        case_profit_pct = 0.10

    group = con.execute(
        "SELECT cost FROM variant_groups WHERE id = ?", (variant_group_id,)
    ).fetchone()
    if not group or group["cost"] <= 0:
        return []

    cases = con.execute(
        "SELECT id, case_qty, name FROM products WHERE is_case = 1 AND case_variant_group_id = ?",
        (variant_group_id,)
    ).fetchall()

    affected = []
    for c in cases:
        qty = c["case_qty"] or 1
        case_cost = round(group["cost"] * qty, 4)
        case_price = round(case_cost * (1 + case_profit_pct), 2)
        con.execute(
            """UPDATE products SET cost = ?, selling_price = ?, updated_at = datetime('now', 'localtime')
               WHERE id = ?""",
            (case_cost, case_price, c["id"])
        )
        affected.append({"id": c["id"], "name": c["name"]})
    return affected


def delete_variant_group(group_id: int):
    """Delete a variant group. Member products fall back to standalone.
    NOTE: their stock resets to 0 (products.stock default) since stock lived
    only on the group — caller should warn the user and prompt a manual
    stock adjustment after deletion."""
    with _conn() as con:
        con.execute("DELETE FROM variant_groups WHERE id = ?", (group_id,))
        con.commit()


def adjust_variant_group_stock(group_id: int, delta: int,
                               reason: str = "Restock", adjusted_by: int = None):
    """Adjust shared stock on a variant group. Clamps at 0 on removal.
    Logged in stock_adjustments via variant_group_id."""
    with _conn() as con:
        if delta < 0:
            con.execute(
                "UPDATE variant_groups SET stock = MAX(0, stock + ?) WHERE id = ?",
                (delta, group_id)
            )
        else:
            con.execute(
                "UPDATE variant_groups SET stock = stock + ? WHERE id = ?",
                (delta, group_id)
            )
        con.execute(
            """INSERT INTO stock_adjustments (variant_group_id, qty_change, reason, adjusted_by)
               VALUES (?, ?, ?, ?)""",
            (group_id, delta, reason, adjusted_by)
        )
        con.commit()


def get_low_stock_variant_groups(threshold: int = 5) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM variant_groups WHERE stock <= ? ORDER BY stock ASC, name",
            (threshold,)
        )]


# ── Products ─────────────────────────────────────────────────────────────────

_PRODUCT_SELECT = """
    SELECT p.*,
           g.name  AS group_name,
           ag.name AS alias_group_name,
           vg.name AS variant_group_name,
           vg.stock AS variant_group_stock,
           -- Effective cost/price/stock — resolves group precedence
           -- (variant > alias > own) so callers never need to re-derive this.
           -- A grouped member's own cost/selling_price/stock columns are
           -- NOT authoritative; always read the effective_* fields instead.
           COALESCE(vg.cost, ag.cost, p.cost)                   AS effective_cost,
           COALESCE(vg.selling_price, ag.selling_price, p.selling_price) AS effective_selling_price,
           COALESCE(vg.stock, p.stock)                          AS effective_stock,
           COALESCE(vg.discount_level1_id, ag.discount_level1_id, p.discount_level1_id) AS effective_discount_level1_id,
           COALESCE(vg.discount_level2_id, ag.discount_level2_id, p.discount_level2_id) AS effective_discount_level2_id,
           COALESCE(vg.inline_discount1_qty, ag.inline_discount1_qty, p.inline_discount1_qty) AS effective_inline_discount1_qty,
           COALESCE(vg.inline_discount1_pct, ag.inline_discount1_pct, p.inline_discount1_pct) AS effective_inline_discount1_pct,
           COALESCE(vg.inline_discount2_qty, ag.inline_discount2_qty, p.inline_discount2_qty) AS effective_inline_discount2_qty,
           COALESCE(vg.inline_discount2_pct, ag.inline_discount2_pct, p.inline_discount2_pct) AS effective_inline_discount2_pct
    FROM   products p
    LEFT   JOIN groups         g  ON g.id  = p.group_id
    LEFT   JOIN alias_groups   ag ON ag.id = p.alias_group_id
    LEFT   JOIN variant_groups vg ON vg.id = p.variant_group_id
"""


def get_products(search: str = "", group_id: int = None,
                 limit: int = 100, offset: int = 0,
                 exclude_cases: bool = False) -> list[dict]:
    q = _PRODUCT_SELECT + " WHERE 1=1"
    params: list = []
    if exclude_cases:
        q += " AND p.is_case = 0"
    if search:
        q += """ AND (LOWER(p.barcode) LIKE ? OR LOWER(p.name) LIKE ?
                   OR LOWER(ag.name)   LIKE ? OR LOWER(vg.name) LIKE ?)"""
        s = f"%{search.lower()}%"
        params += [s, s, s, s]
    if group_id is not None:
        q += " AND p.group_id = ?"
        params.append(group_id)
    q += " ORDER BY p.name COLLATE NOCASE LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_product_by_id(product_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(_PRODUCT_SELECT + " WHERE p.id = ?", (product_id,)).fetchone()
        return dict(row) if row else None


def get_product_by_barcode(barcode: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            _PRODUCT_SELECT + " WHERE p.barcode = ?", (barcode.strip().upper(),)
        ).fetchone()
        return dict(row) if row else None


def add_product(barcode: str, name: str, cost: float, selling_price: float,
                group_id: int = None,
                alias_group_id: int = None, variant_group_id: int = None,
                gct_applicable: bool = True, is_case: bool = False,
                case_qty: int = None, case_product_id: int = None,
                case_variant_group_id: int = None,
                discount_level1_id: int = None, discount_level2_id: int = None,
                inline_discount1_qty: int = None, inline_discount1_pct: float = None,
                inline_discount2_qty: int = None, inline_discount2_pct: float = None,
                stock: int = 0) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO products
               (barcode, name, cost, selling_price, group_id,
                alias_group_id, variant_group_id,
                gct_applicable, is_case, case_qty, case_product_id, case_variant_group_id,
                discount_level1_id, discount_level2_id,
                inline_discount1_qty, inline_discount1_pct,
                inline_discount2_qty, inline_discount2_pct,
                stock)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (barcode.strip().upper(), name.strip().upper(),
             cost, selling_price, group_id,
             alias_group_id, variant_group_id,
             int(gct_applicable), int(is_case), case_qty, case_product_id, case_variant_group_id,
             discount_level1_id, discount_level2_id,
             inline_discount1_qty, inline_discount1_pct,
             inline_discount2_qty, inline_discount2_pct,
             stock)
        )
        con.commit()
        return cur.lastrowid


def update_product(product_id: int, **fields) -> bool:
    if not fields:
        return False
    for key in ("name", "barcode"):
        if key in fields and isinstance(fields[key], str):
            fields[key] = fields[key].strip().upper()
    set_parts = [f"{k} = ?" for k in fields]
    params = list(fields.values())
    set_parts.append("updated_at = datetime('now', 'localtime')")
    params.append(product_id)
    sql = f"UPDATE products SET {', '.join(set_parts)} WHERE id = ?"
    with _conn() as con:
        cur = con.execute(sql, params)
        con.commit()
        return cur.rowcount > 0


def delete_product(product_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM products WHERE id = ?", (product_id,))
        con.commit()
        return cur.rowcount > 0


def count_products(search: str = "", group_id: int = None,
                   exclude_cases: bool = False) -> int:
    q = """SELECT COUNT(*) FROM products p
           LEFT JOIN alias_groups   ag ON ag.id = p.alias_group_id
           LEFT JOIN variant_groups vg ON vg.id = p.variant_group_id
           WHERE 1=1"""
    params: list = []
    if exclude_cases:
        q += " AND p.is_case = 0"
    if search:
        q += """ AND (LOWER(p.barcode) LIKE ? OR LOWER(p.name) LIKE ?
                   OR LOWER(ag.name)   LIKE ? OR LOWER(vg.name) LIKE ?)"""
        s = f"%{search.lower()}%"
        params += [s, s, s, s]
    if group_id is not None:
        q += " AND p.group_id = ?"
        params.append(group_id)
    with _conn() as con:
        return con.execute(q, params).fetchone()[0]


# ── Cost cascades (single product -> its cases) ─────────────────────────────

def cascade_single_cost_to_cases(single_product_id: int) -> list[dict]:
    """When a standalone single product's cost changes, update case products
    linked to it via case_product_id. (Products in an alias/variant group use
    cascade_alias_group_to_cases / cascade_variant_group_to_cases instead —
    a group member's own `cost` column isn't authoritative.)"""
    from core.db_config import get as cfg_get
    try:
        case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
    except (ValueError, TypeError):
        case_profit_pct = 0.10

    with _conn() as con:
        single = con.execute(
            "SELECT cost FROM products WHERE id = ?", (single_product_id,)
        ).fetchone()
        if not single or single["cost"] <= 0:
            return []

        cases = con.execute(
            "SELECT id, case_qty, name FROM products WHERE is_case = 1 AND case_product_id = ?",
            (single_product_id,)
        ).fetchall()

        affected = []
        for c in cases:
            qty = c["case_qty"] or 1
            case_cost = round(single["cost"] * qty, 4)
            case_price = round(case_cost * (1 + case_profit_pct), 2)
            con.execute(
                """UPDATE products SET cost = ?, selling_price = ?, updated_at = datetime('now', 'localtime')
                   WHERE id = ?""",
                (case_cost, case_price, c["id"])
            )
            affected.append({"id": c["id"], "name": c["name"]})
        con.commit()
        return affected


def recalculate_all_cases(case_profit_pct: float = None) -> int:
    """Recalculate cost/selling_price for every case product from its linked
    source (single product via case_product_id, or variant group via
    case_variant_group_id). Returns count of case products updated.

    Skips case products with no link or a zero-cost source — same rule
    the per-link cascade functions use.
    """
    if case_profit_pct is None:
        from core.db_config import get as cfg_get
        try:
            case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
        except (ValueError, TypeError):
            case_profit_pct = 0.10

    with _conn() as con:
        cases = con.execute(
            """SELECT id, case_qty, case_product_id, case_variant_group_id
               FROM products WHERE is_case = 1"""
        ).fetchall()

        updated = 0
        for c in cases:
            qty = c["case_qty"] or 1
            source_cost = None
            if c["case_product_id"]:
                row = con.execute(
                    "SELECT cost FROM products WHERE id = ?", (c["case_product_id"],)
                ).fetchone()
                source_cost = row["cost"] if row else None
            elif c["case_variant_group_id"]:
                row = con.execute(
                    "SELECT cost FROM variant_groups WHERE id = ?", (c["case_variant_group_id"],)
                ).fetchone()
                source_cost = row["cost"] if row else None

            if not source_cost or source_cost <= 0:
                continue

            case_cost = round(source_cost * qty, 4)
            case_price = round(case_cost * (1 + case_profit_pct), 2)
            con.execute(
                "UPDATE products SET cost = ?, selling_price = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
                (case_cost, case_price, c["id"])
            )
            updated += 1
        con.commit()
        return updated


# ── Stock ─────────────────────────────────────────────────────────────────────
#
# Resolution rule for a product row:
#   - variant_group_id set  -> stock lives on variant_groups.stock
#   - alias_group_id set    -> stock lives on products.stock (own)
#   - standalone             -> stock lives on products.stock (own)
#   - is_case, case_product_id set        -> selling decrements the SINGLE's stock
#   - is_case, case_variant_group_id set  -> selling decrements the GROUP's stock

def decrement_stock(product_id: int, qty: int):
    """Decrement stock for a sale. Clamps at 0."""
    with _conn() as con:
        p = con.execute(
            """SELECT is_case, case_qty, case_product_id, case_variant_group_id,
                      alias_group_id, variant_group_id
               FROM products WHERE id = ?""",
            (product_id,)
        ).fetchone()
        if not p:
            return

        if p["is_case"] and p["case_variant_group_id"]:
            units = (p["case_qty"] or 1) * qty
            con.execute(
                "UPDATE variant_groups SET stock = MAX(0, stock - ?) WHERE id = ?",
                (units, p["case_variant_group_id"])
            )
            con.execute(
                """INSERT INTO stock_adjustments (variant_group_id, qty_change, reason)
                   VALUES (?, ?, 'Sale')""",
                (p["case_variant_group_id"], -units)
            )
        elif p["is_case"] and p["case_product_id"]:
            units = (p["case_qty"] or 1) * qty
            con.execute(
                "UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?",
                (units, p["case_product_id"])
            )
        elif p["variant_group_id"]:
            con.execute(
                "UPDATE variant_groups SET stock = MAX(0, stock - ?) WHERE id = ?",
                (qty, p["variant_group_id"])
            )
            con.execute(
                """INSERT INTO stock_adjustments (variant_group_id, qty_change, reason)
                   VALUES (?, ?, 'Sale')""",
                (p["variant_group_id"], -qty)
            )
        else:
            # Standalone or alias-group member — own stock
            con.execute(
                "UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?",
                (qty, product_id)
            )
        con.commit()


def increment_stock(product_id: int, qty: int):
    """Increment stock for a void/refund."""
    with _conn() as con:
        p = con.execute(
            """SELECT is_case, case_qty, case_product_id, case_variant_group_id,
                      alias_group_id, variant_group_id
               FROM products WHERE id = ?""",
            (product_id,)
        ).fetchone()
        if not p:
            return

        if p["is_case"] and p["case_variant_group_id"]:
            units = (p["case_qty"] or 1) * qty
            con.execute(
                "UPDATE variant_groups SET stock = stock + ? WHERE id = ?",
                (units, p["case_variant_group_id"])
            )
            con.execute(
                """INSERT INTO stock_adjustments (variant_group_id, qty_change, reason)
                   VALUES (?, ?, 'Void/Refund')""",
                (p["case_variant_group_id"], units)
            )
        elif p["is_case"] and p["case_product_id"]:
            units = (p["case_qty"] or 1) * qty
            con.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (units, p["case_product_id"])
            )
        elif p["variant_group_id"]:
            con.execute(
                "UPDATE variant_groups SET stock = stock + ? WHERE id = ?",
                (qty, p["variant_group_id"])
            )
            con.execute(
                """INSERT INTO stock_adjustments (variant_group_id, qty_change, reason)
                   VALUES (?, ?, 'Void/Refund')""",
                (p["variant_group_id"], qty)
            )
        else:
            con.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (qty, product_id)
            )
        con.commit()


def adjust_stock(product_id: int, qty_change: int,
                 reason: str = "Restock", adjusted_by: int = None):
    """Manually adjust stock for a product. If the product is a variant-group
    member, this adjusts the GROUP's shared stock instead (and logs against
    variant_group_id) since the member has no independent stock of its own."""
    with _conn() as con:
        p = con.execute(
            "SELECT variant_group_id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not p:
            return

        if p["variant_group_id"]:
            adjust_variant_group_stock(p["variant_group_id"], qty_change, reason, adjusted_by)
            return

        if qty_change < 0:
            con.execute(
                "UPDATE products SET stock = MAX(0, stock + ?) WHERE id = ?",
                (qty_change, product_id)
            )
        else:
            con.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (qty_change, product_id)
            )
        con.execute(
            """INSERT INTO stock_adjustments (product_id, qty_change, reason, adjusted_by)
               VALUES (?, ?, ?, ?)""",
            (product_id, qty_change, reason, adjusted_by)
        )
        con.commit()


def get_stock_adjustments(product_id: int = None, variant_group_id: int = None,
                          limit: int = 20) -> list[dict]:
    with _conn() as con:
        if variant_group_id is not None:
            return [dict(r) for r in con.execute(
                """SELECT sa.*, vg.name AS source_name
                   FROM stock_adjustments sa
                   JOIN variant_groups vg ON vg.id = sa.variant_group_id
                   WHERE sa.variant_group_id = ?
                   ORDER BY sa.adjusted_at DESC LIMIT ?""",
                (variant_group_id, limit)
            )]
        return [dict(r) for r in con.execute(
            """SELECT sa.*, p.name AS source_name
               FROM stock_adjustments sa
               JOIN products p ON p.id = sa.product_id
               WHERE sa.product_id = ?
               ORDER BY sa.adjusted_at DESC LIMIT ?""",
            (product_id, limit)
        )]


def get_all_stock_adjustments(search: str = "", limit: int = 100) -> list[dict]:
    """Recent stock adjustments across products AND variant groups, merged."""
    q = """
        SELECT sa.id, sa.qty_change, sa.reason, sa.adjusted_by, sa.adjusted_at,
               COALESCE(p.name, vg.name) AS source_name,
               CASE WHEN sa.variant_group_id IS NOT NULL THEN 'variant_group' ELSE 'product' END AS source_type
        FROM   stock_adjustments sa
        LEFT   JOIN products       p  ON p.id  = sa.product_id
        LEFT   JOIN variant_groups vg ON vg.id = sa.variant_group_id
        WHERE  1=1
    """
    params: list = []
    if search:
        q += " AND LOWER(COALESCE(p.name, vg.name)) LIKE ?"
        params.append(f"%{search.lower()}%")
    q += " ORDER BY sa.adjusted_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_low_stock_products(threshold: int = 5) -> list[dict]:
    """Standalone/alias-member products at or below threshold. Excludes case
    products and variant-group members (use get_low_stock_variant_groups for those)."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            """SELECT p.*, g.name AS group_name
               FROM   products p
               LEFT   JOIN groups g ON g.id = p.group_id
               WHERE  p.stock <= ? AND p.is_case = 0 AND p.variant_group_id IS NULL
               ORDER  BY p.stock ASC, p.name""",
            (threshold,)
        )]
