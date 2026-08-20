"""
core/db_products.py
Products database.

Tables
------
price_groups  — named groups for price-linked products (alias or variant)
groups        — product groups with profit margins
products      — main product records
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
CREATE TABLE IF NOT EXISTS price_groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    type          TEXT    NOT NULL DEFAULT 'alias'
                          CHECK(type IN ('alias','variant','case_group')),
    cost          REAL    NOT NULL DEFAULT 0.0,
    selling_price REAL    NOT NULL DEFAULT 0.0,
    -- case_group only: units per case and shared pool stock
    case_qty      INTEGER DEFAULT NULL,
    pool_stock    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    profit_margin REAL    NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode          TEXT    NOT NULL UNIQUE,
    name             TEXT    NOT NULL,
    cost             REAL    NOT NULL DEFAULT 0.0,
    selling_price    REAL    NOT NULL DEFAULT 0.0,
    group_id         INTEGER REFERENCES groups(id)       ON DELETE SET NULL,
    alias_group_id   INTEGER REFERENCES price_groups(id) ON DELETE SET NULL,
    variant_group_id INTEGER REFERENCES price_groups(id) ON DELETE SET NULL,
    discount_level1  INTEGER DEFAULT NULL,
    discount_level2  INTEGER DEFAULT NULL,
    inline_disc1_qty INTEGER DEFAULT NULL,
    inline_disc1_pct REAL    DEFAULT NULL,
    inline_disc2_qty INTEGER DEFAULT NULL,
    inline_disc2_pct REAL    DEFAULT NULL,
    gct_applicable   INTEGER NOT NULL DEFAULT 1,
    is_case          INTEGER NOT NULL DEFAULT 0,
    case_qty         INTEGER DEFAULT NULL,
    case_product_id  INTEGER REFERENCES products(id)     ON DELETE SET NULL,
    case_group_id    INTEGER REFERENCES price_groups(id) ON DELETE SET NULL,
    stock            INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stock_adjustments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty_change  INTEGER NOT NULL,
    reason      TEXT    NOT NULL DEFAULT 'Restock',
    adjusted_by INTEGER DEFAULT NULL,
    adjusted_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pool_stock_adjustments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    case_group_id  INTEGER NOT NULL REFERENCES price_groups(id) ON DELETE CASCADE,
    qty_change     INTEGER NOT NULL,
    reason         TEXT    NOT NULL DEFAULT 'Restock',
    adjusted_by    INTEGER DEFAULT NULL,
    adjusted_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_products_barcode    ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_products_name       ON products(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_products_alias_pg   ON products(alias_group_id);
CREATE INDEX IF NOT EXISTS idx_products_var_pg     ON products(variant_group_id);
CREATE INDEX IF NOT EXISTS idx_products_case_grp   ON products(case_group_id);
CREATE INDEX IF NOT EXISTS idx_pool_adj_group      ON pool_stock_adjustments(case_group_id);
"""


def init_db():
    """Create tables and migrate existing schema."""
    with _conn() as con:
        # ── Step 1: migrate products table BEFORE running full SCHEMA ──
        # Check if products table exists at all
        has_products = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
        ).fetchone()

        if has_products:
            cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
            if "brand" in cols:
                # Recreate without brand, with new columns
                con.executescript("""
                    PRAGMA foreign_keys=OFF;
                    CREATE TABLE IF NOT EXISTS price_groups (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        name          TEXT    NOT NULL UNIQUE,
                        type          TEXT    NOT NULL DEFAULT 'alias'
                                              CHECK(type IN ('alias','variant')),
                        selling_price REAL    NOT NULL DEFAULT 0.0
                    );
                    CREATE TABLE IF NOT EXISTS groups (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        name          TEXT    NOT NULL UNIQUE,
                        profit_margin REAL    NOT NULL DEFAULT 0.0
                    );
                    CREATE TABLE products_new (
                        id               INTEGER PRIMARY KEY AUTOINCREMENT,
                        barcode          TEXT    NOT NULL UNIQUE,
                        name             TEXT    NOT NULL,
                        cost             REAL    NOT NULL DEFAULT 0.0,
                        selling_price    REAL    NOT NULL DEFAULT 0.0,
                        group_id         INTEGER REFERENCES groups(id)       ON DELETE SET NULL,
                        alias_group_id   INTEGER REFERENCES price_groups(id) ON DELETE SET NULL,
                        variant_group_id INTEGER REFERENCES price_groups(id) ON DELETE SET NULL,
                        discount_level1  INTEGER DEFAULT NULL,
                        discount_level2  INTEGER DEFAULT NULL,
                        gct_applicable   INTEGER NOT NULL DEFAULT 1,
                        is_case          INTEGER NOT NULL DEFAULT 0,
                        case_qty         INTEGER DEFAULT NULL,
                        case_product_id  INTEGER REFERENCES products(id)     ON DELETE SET NULL,
                        stock            INTEGER NOT NULL DEFAULT 0,
                        created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                        updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
                    );
                    INSERT INTO products_new
                        (id, barcode, name, cost, selling_price, group_id,
                         discount_level1, discount_level2, gct_applicable,
                         is_case, case_qty, case_product_id, stock,
                         created_at, updated_at)
                    SELECT id, barcode, name, cost, selling_price, group_id,
                           discount_level1, discount_level2, gct_applicable,
                           is_case, case_qty, case_product_id, stock,
                           created_at, updated_at
                    FROM products;
                    DROP TABLE products;
                    ALTER TABLE products_new RENAME TO products;
                    DROP TABLE IF EXISTS product_alias;
                    PRAGMA foreign_keys=ON;
                """)
                con.commit()
            else:
                # Add new columns if missing
                for col, defn in [
                    ("alias_group_id",   "INTEGER REFERENCES price_groups(id) ON DELETE SET NULL"),
                    ("variant_group_id", "INTEGER REFERENCES price_groups(id) ON DELETE SET NULL"),
                    ("inline_disc1_qty", "INTEGER DEFAULT NULL"),
                    ("inline_disc1_pct", "REAL DEFAULT NULL"),
                    ("inline_disc2_qty", "INTEGER DEFAULT NULL"),
                    ("inline_disc2_pct", "REAL DEFAULT NULL"),
                ]:
                    if col not in cols:
                        con.execute(f"ALTER TABLE products ADD COLUMN {col} {defn}")
                con.execute("DROP TABLE IF EXISTS product_alias")
                con.commit()

        # ── Step 2: create any still-missing tables ────────────────────
        con.executescript(SCHEMA)

        # ── Step 2b: ensure discount_levels table exists ───────────────
        # This table was originally created only by migrate_db.py,
        # but must be present on fresh installs too.
        con.execute("""
            CREATE TABLE IF NOT EXISTS discount_levels (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL DEFAULT '',
                discount_percent REAL    NOT NULL DEFAULT 0.0,
                min_quantity     INTEGER NOT NULL DEFAULT 1,
                UNIQUE(min_quantity, discount_percent)
            )
        """)
        # Add unique index to existing DBs that were created without the constraint
        try:
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_disc_levels_unique ON discount_levels(min_quantity, discount_percent)
            """)
        except Exception:
            pass
        # Seed two default levels if the table is empty
        if con.execute("SELECT COUNT(*) FROM discount_levels").fetchone()[0] == 0:
            con.execute("INSERT OR IGNORE INTO discount_levels (name, discount_percent, min_quantity) "
                        "VALUES ('Level 1 - Bulk', 5.0, 6)")
            con.execute("INSERT OR IGNORE INTO discount_levels (name, discount_percent, min_quantity) "
                        "VALUES ('Level 2 - Wholesale', 10.0, 12)")

        # ── Step 3: migrate groups table ──────────────────────────────
        gcols = {r[1] for r in con.execute("PRAGMA table_info(groups)")}
        if "profit_margin" not in gcols:
            con.execute("ALTER TABLE groups ADD COLUMN profit_margin REAL NOT NULL DEFAULT 0.0")

        # ── Step 3b: migrate price_groups — add case_group columns ────
        pgcols = {r[1] for r in con.execute("PRAGMA table_info(price_groups)")}
        for col, defn in [
            ("cost",       "REAL    NOT NULL DEFAULT 0.0"),
            ("case_qty",   "INTEGER DEFAULT NULL"),
            ("pool_stock", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in pgcols:
                con.execute(f"ALTER TABLE price_groups ADD COLUMN {col} {defn}")
        # Widen the CHECK constraint on type to include 'case_group'.
        # SQLite doesn't support ALTER COLUMN so we check the existing SQL;
        # if it's missing case_group we recreate the table.
        pg_sql = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='price_groups'"
        ).fetchone()
        if pg_sql and "case_group" not in pg_sql[0]:
            con.executescript("""
                PRAGMA foreign_keys=OFF;
                CREATE TABLE price_groups_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL UNIQUE,
                    type          TEXT    NOT NULL DEFAULT 'alias'
                                          CHECK(type IN ('alias','variant','case_group')),
                    cost          REAL    NOT NULL DEFAULT 0.0,
                    selling_price REAL    NOT NULL DEFAULT 0.0,
                    case_qty      INTEGER DEFAULT NULL,
                    pool_stock    INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO price_groups_new (id, name, type, cost, selling_price, case_qty, pool_stock)
                SELECT id, name, type,
                       COALESCE(cost, 0.0),
                       COALESCE(selling_price, 0.0),
                       case_qty,
                       COALESCE(pool_stock, 0)
                FROM price_groups;
                DROP TABLE price_groups;
                ALTER TABLE price_groups_new RENAME TO price_groups;
                PRAGMA foreign_keys=ON;
            """)
            con.commit()

        # ── Step 3c: migrate products — add case_group_id ─────────────
        if has_products:
            cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
            if "case_group_id" not in cols:
                con.execute(
                    "ALTER TABLE products ADD COLUMN "
                    "case_group_id INTEGER REFERENCES price_groups(id) ON DELETE SET NULL"
                )

        # ── Step 4: fix stock_adjustments — remove cross-DB FK to users ──
        # Recreate without the REFERENCES users(id) which causes errors
        # since users live in a separate DB file
        has_sa = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_adjustments'"
        ).fetchone()
        if has_sa:
            sa_cols = {r[1] for r in con.execute("PRAGMA table_info(stock_adjustments)")}
            # Check if old FK definition exists by inspecting CREATE TABLE sql
            sa_sql = con.execute(
                "SELECT sql FROM sqlite_master WHERE name='stock_adjustments'"
            ).fetchone()
            if sa_sql and "REFERENCES users" in sa_sql[0]:
                con.executescript("""
                    PRAGMA foreign_keys=OFF;
                    CREATE TABLE stock_adjustments_new (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                        qty_change  INTEGER NOT NULL,
                        reason      TEXT    NOT NULL DEFAULT 'Restock',
                        adjusted_by INTEGER DEFAULT NULL,
                        adjusted_at TEXT    NOT NULL DEFAULT (datetime('now'))
                    );
                    INSERT INTO stock_adjustments_new
                        SELECT id, product_id, qty_change, reason, adjusted_by, adjusted_at
                        FROM stock_adjustments;
                    DROP TABLE stock_adjustments;
                    ALTER TABLE stock_adjustments_new RENAME TO stock_adjustments;
                    PRAGMA foreign_keys=ON;
                """)

        con.commit()


# ── Price Groups ──────────────────────────────────────────────────────────────

def get_price_groups(type_: str = None) -> list[dict]:
    q = "SELECT * FROM price_groups"
    params = []
    if type_:
        q += " WHERE type = ?"
        params.append(type_)
    q += " ORDER BY name"
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def add_price_group(name: str, type_: str, selling_price: float = 0.0) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO price_groups (name, type, selling_price) VALUES (?, ?, ?)",
            (name.strip().upper(), type_, selling_price)
        )
        con.commit()
        return cur.lastrowid


def update_price_group(group_id: int, name: str = None,
                       cost: float = None,
                       selling_price: float = None) -> list[dict]:
    """Update a price group record and cascade cost/selling_price to all members."""
    with _conn() as con:
        if name:
            con.execute("UPDATE price_groups SET name = ? WHERE id = ?",
                        (name.strip().upper(), group_id))

        set_clauses, params = [], []
        if cost is not None:
            set_clauses.append("cost = ?"); params.append(cost)
        if selling_price is not None:
            set_clauses.append("selling_price = ?"); params.append(selling_price)

        affected = []
        if set_clauses:
            params.append(group_id)
            con.execute(
                f"UPDATE price_groups SET {', '.join(set_clauses)} WHERE id = ?",
                params
            )
            # Collect affected products
            affected = [dict(r) for r in con.execute(
                "SELECT id, name FROM products WHERE alias_group_id = ? OR variant_group_id = ?",
                (group_id, group_id)
            )]
            # Build product UPDATE
            prod_set, prod_params = [], []
            if cost is not None:
                prod_set.append("cost = ?"); prod_params.append(cost)
            if selling_price is not None:
                prod_set.append("selling_price = ?"); prod_params.append(selling_price)
            prod_params += [group_id, group_id]
            con.execute(
                f"""UPDATE products SET {', '.join(prod_set)}, updated_at = datetime('now')
                    WHERE alias_group_id = ? OR variant_group_id = ?""",
                prod_params
            )

        con.commit()
        return affected


def delete_price_group(group_id: int):
    with _conn() as con:
        con.execute("DELETE FROM price_groups WHERE id = ?", (group_id,))
        con.commit()


# ── Case Groups ───────────────────────────────────────────────────────────────

def get_case_groups() -> list[dict]:
    """Return all case_group price groups, ordered by name."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM price_groups WHERE type = 'case_group' ORDER BY name"
        )]


def get_case_group_by_id(group_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM price_groups WHERE id = ? AND type = 'case_group'",
            (group_id,)
        ).fetchone()
        return dict(row) if row else None


def add_case_group(name: str, case_qty: int,
                   cost: float = 0.0, selling_price: float = 0.0) -> int:
    """Create a new shared-pool case group.

    Returns the new group id.
    Raises ValueError if a group with the same name already exists.
    """
    clean = name.strip().upper()
    with _conn() as con:
        existing = con.execute(
            "SELECT id FROM price_groups WHERE name = ? AND type = 'case_group'",
            (clean,)
        ).fetchone()
        if existing:
            raise ValueError(f'A case group named "{clean}" already exists.')
        cur = con.execute(
            """INSERT INTO price_groups (name, type, cost, selling_price, case_qty, pool_stock)
               VALUES (?, 'case_group', ?, ?, ?, 0)""",
            (clean, cost, selling_price, case_qty)
        )
        con.commit()
        return cur.lastrowid


def update_case_group(group_id: int, name: str = None, case_qty: int = None,
                      cost: float = None, selling_price: float = None) -> list[dict]:
    """Update a case group's metadata and cascade cost/price to all member case products.

    Returns the list of affected product dicts (id, name).
    """
    with _conn() as con:
        sets, params = [], []
        if name is not None:
            sets.append("name = ?"); params.append(name.strip().upper())
        if case_qty is not None:
            sets.append("case_qty = ?"); params.append(case_qty)
        if cost is not None:
            sets.append("cost = ?"); params.append(cost)
        if selling_price is not None:
            sets.append("selling_price = ?"); params.append(selling_price)
        if sets:
            params.append(group_id)
            con.execute(f"UPDATE price_groups SET {', '.join(sets)} WHERE id = ?", params)

        # Cascade cost + price to all member case products
        affected = []
        if cost is not None or selling_price is not None:
            members = con.execute(
                "SELECT id, name FROM products WHERE case_group_id = ?", (group_id,)
            ).fetchall()
            p_sets, p_params = [], []
            if cost is not None:
                p_sets.append("cost = ?"); p_params.append(cost)
            if selling_price is not None:
                p_sets.append("selling_price = ?"); p_params.append(selling_price)
            p_params.append(group_id)
            con.execute(
                f"UPDATE products SET {', '.join(p_sets)}, updated_at = datetime('now') "
                f"WHERE case_group_id = ?",
                p_params
            )
            affected = [dict(r) for r in members]

        con.commit()
        return affected


def delete_case_group(group_id: int):
    """Delete a case group. Member products will have case_group_id set to NULL (FK cascade)."""
    with _conn() as con:
        con.execute("DELETE FROM price_groups WHERE id = ? AND type = 'case_group'", (group_id,))
        con.commit()


def adjust_case_group_stock(group_id: int, delta: int,
                             reason: str = "Restock", adjusted_by: int = None):
    """Adjust the shared pool stock for a case group.

    delta > 0 = cases received; delta < 0 = cases sold / corrected.
    Pool stock is clamped to 0 on removal.
    Records in pool_stock_adjustments for the audit trail.
    """
    with _conn() as con:
        if delta < 0:
            con.execute(
                "UPDATE price_groups SET pool_stock = MAX(0, pool_stock + ?) WHERE id = ?",
                (delta, group_id)
            )
        else:
            con.execute(
                "UPDATE price_groups SET pool_stock = pool_stock + ? WHERE id = ?",
                (delta, group_id)
            )
        con.execute(
            """INSERT INTO pool_stock_adjustments
               (case_group_id, qty_change, reason, adjusted_by)
               VALUES (?, ?, ?, ?)""",
            (group_id, delta, reason, adjusted_by)
        )
        con.commit()


def get_pool_stock_adjustments(group_id: int, limit: int = 20) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            """SELECT psa.*, pg.name AS group_name
               FROM pool_stock_adjustments psa
               JOIN price_groups pg ON pg.id = psa.case_group_id
               WHERE psa.case_group_id = ?
               ORDER BY psa.adjusted_at DESC LIMIT ?""",
            (group_id, limit)
        )]


def get_low_stock_case_groups(threshold: int = 3) -> list[dict]:
    """Case groups whose pool stock is at or below the threshold."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            """SELECT * FROM price_groups
               WHERE type = 'case_group' AND pool_stock <= ?
               ORDER BY pool_stock ASC, name""",
            (threshold,)
        )]


# ── Product Groups ────────────────────────────────────────────────────────────

def get_groups() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute("SELECT * FROM groups ORDER BY name")]


def add_group(name: str) -> int:
    with _conn() as con:
        cur = con.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)",
                          (name.strip().upper(),))
        con.commit()
        return cur.lastrowid


def update_group_margin(group_id: int, profit_margin: float):
    with _conn() as con:
        con.execute("UPDATE groups SET profit_margin = ? WHERE id = ?",
                    (profit_margin, group_id))
        con.commit()
    recalculate_selling_prices(group_id=group_id)


def recalculate_selling_prices(group_id: int = None):
    """Recalculate selling_price = cost × (1 + profit_margin) for group products."""
    with _conn() as con:
        if group_id is not None:
            rows = con.execute(
                "SELECT p.id, p.cost, g.profit_margin "
                "FROM products p JOIN groups g ON g.id = p.group_id "
                "WHERE p.group_id = ? AND p.cost > 0",
                (group_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT p.id, p.cost, g.profit_margin "
                "FROM products p JOIN groups g ON g.id = p.group_id "
                "WHERE p.cost > 0"
            ).fetchall()
        for row in rows:
            new_price = round(row["cost"] * (1 + row["profit_margin"]), 2)
            con.execute("UPDATE products SET selling_price = ? WHERE id = ?",
                        (new_price, row["id"]))
        con.commit()


def recalculate_all_cases(case_profit_pct: float = None) -> int:
    """Recalculate selling_price for every case product.

    A case product's selling price = its own cost × (1 + case_profit_pct).
    If *case_profit_pct* is not supplied it is read from the settings DB.

    Also ensures each case product's cost is in sync with its parent single:
        case.cost = single.cost × case.case_qty

    Returns the number of case products updated.
    """
    if case_profit_pct is None:
        from core.db_config import get as cfg_get
        try:
            case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
        except (ValueError, TypeError):
            case_profit_pct = 0.10

    with _conn() as con:
        cases = con.execute(
            """SELECT p.id, p.cost, p.case_qty, p.case_product_id
               FROM products p
               WHERE p.is_case = 1"""
        ).fetchall()

        updated = 0
        for c in cases:
            cost = c["cost"]

            # Sync cost from parent single if linked
            if c["case_product_id"] and c["case_qty"]:
                parent = con.execute(
                    "SELECT cost FROM products WHERE id = ?",
                    (c["case_product_id"],)
                ).fetchone()
                if parent and parent["cost"] > 0:
                    cost = round(parent["cost"] * c["case_qty"], 4)
                    con.execute(
                        "UPDATE products SET cost = ?, updated_at = datetime('now') WHERE id = ?",
                        (cost, c["id"])
                    )

            if cost > 0:
                new_price = round(cost * (1 + case_profit_pct), 2)
                con.execute(
                    "UPDATE products SET selling_price = ?, updated_at = datetime('now') WHERE id = ?",
                    (new_price, c["id"])
                )
                updated += 1

        con.commit()
    return updated


def cascade_single_cost_to_cases(single_product_id: int) -> int:
    """When a single product's cost changes, update linked case products.

    Updates each case product that references *single_product_id*:
      - case.cost = single.cost × case.case_qty
      - case.selling_price = case.cost × (1 + case_profit_pct)

    Returns the number of case products updated.
    """
    from core.db_config import get as cfg_get
    try:
        case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
    except (ValueError, TypeError):
        case_profit_pct = 0.10

    with _conn() as con:
        single = con.execute(
            "SELECT cost FROM products WHERE id = ?",
            (single_product_id,)
        ).fetchone()
        if not single or single["cost"] <= 0:
            return 0

        single_cost = single["cost"]
        cases = con.execute(
            "SELECT id, case_qty FROM products WHERE is_case = 1 AND case_product_id = ?",
            (single_product_id,)
        ).fetchall()

        updated = 0
        for c in cases:
            qty = c["case_qty"] or 1
            case_cost  = round(single_cost * qty, 4)
            case_price = round(case_cost * (1 + case_profit_pct), 2)
            con.execute(
                """UPDATE products
                   SET cost = ?, selling_price = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (case_cost, case_price, c["id"])
            )
            updated += 1

        con.commit()
    return updated


def delete_group(group_id: int):
    with _conn() as con:
        con.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        con.commit()


# ── Products ──────────────────────────────────────────────────────────────────

def get_discount_levels() -> list[dict]:
    """Return all discount levels as a list of dicts, ordered by min_quantity."""
    with _conn() as con:
        try:
            rows = con.execute(
                "SELECT id, name, min_quantity, discount_percent FROM discount_levels "
                "ORDER BY min_quantity"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


def get_products(search: str = "", group_id: int = None,
                 limit: int = 100, offset: int = 0,
                 exclude_cases: bool = False) -> list[dict]:
    q = """
        SELECT p.*,
               g.name  AS group_name,
               ag.name AS alias_group_name,
               vg.name AS variant_group_name
        FROM   products p
        LEFT   JOIN groups       g  ON g.id  = p.group_id
        LEFT   JOIN price_groups ag ON ag.id = p.alias_group_id
        LEFT   JOIN price_groups vg ON vg.id = p.variant_group_id
        WHERE  1=1
    """
    params: list = []
    if exclude_cases:
        q += " AND p.is_case = 0"
    if search:
        q += """
          AND (LOWER(p.barcode) LIKE ?
            OR LOWER(p.name)    LIKE ?
            OR LOWER(ag.name)   LIKE ?
            OR LOWER(vg.name)   LIKE ?)
        """
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
        row = con.execute(
            """SELECT p.*, g.name AS group_name,
                      ag.name AS alias_group_name,
                      vg.name AS variant_group_name
               FROM products p
               LEFT JOIN groups       g  ON g.id  = p.group_id
               LEFT JOIN price_groups ag ON ag.id = p.alias_group_id
               LEFT JOIN price_groups vg ON vg.id = p.variant_group_id
               WHERE p.id = ?""",
            (product_id,)
        ).fetchone()
        return dict(row) if row else None


def get_product_by_barcode(barcode: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            """SELECT p.*, g.name AS group_name,
                      ag.name AS alias_group_name,
                      vg.name AS variant_group_name
               FROM products p
               LEFT JOIN groups       g  ON g.id  = p.group_id
               LEFT JOIN price_groups ag ON ag.id = p.alias_group_id
               LEFT JOIN price_groups vg ON vg.id = p.variant_group_id
               WHERE p.barcode = ?""",
            (barcode.strip().upper(),)
        ).fetchone()
        return dict(row) if row else None


def add_product(barcode: str, name: str, cost: float,
                selling_price: float, group_id: int = None,
                alias_group_id: int = None, variant_group_id: int = None,
                gct_applicable: bool = True, is_case: bool = False,
                case_qty: int = None, case_product_id: int = None,
                case_group_id: int = None,
                discount_level1: int = None, discount_level2: int = None,
                inline_disc1_qty: int = None, inline_disc1_pct: float = None,
                inline_disc2_qty: int = None, inline_disc2_pct: float = None,
                stock: int = 0) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO products
               (barcode, name, cost, selling_price, group_id,
                alias_group_id, variant_group_id,
                gct_applicable, is_case, case_qty, case_product_id, case_group_id,
                discount_level1, discount_level2,
                inline_disc1_qty, inline_disc1_pct,
                inline_disc2_qty, inline_disc2_pct,
                stock)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (barcode.strip().upper(), name.strip().upper(),
             cost, selling_price, group_id,
             alias_group_id, variant_group_id,
             int(gct_applicable), int(is_case), case_qty, case_product_id, case_group_id,
             discount_level1, discount_level2,
             inline_disc1_qty, inline_disc1_pct,
             inline_disc2_qty, inline_disc2_pct,
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
    set_parts = []
    params = []
    for k, v in fields.items():
        if k == "updated_at":
            set_parts.append("updated_at = datetime('now')")
        else:
            set_parts.append(f"{k} = ?")
            params.append(v)
    set_parts.append("updated_at = datetime('now')")
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


# ── Stock ─────────────────────────────────────────────────────────────────────

def decrement_stock(product_id: int, qty: int):
    """Decrement stock for a sale. Handles both case modes automatically.

    Mode 1 (case_product_id set): decrements the parent single product's
    stock by case_qty x qty sold.

    Mode 2 (case_group_id set): decrements the shared pool stock on the
    case group by qty sold (1 case = 1 unit off the pool).

    Plain single products: decrements own stock by qty.
    Clamps at 0 in all cases.
    """
    with _conn() as con:
        p = con.execute(
            "SELECT is_case, case_qty, case_product_id, case_group_id FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
        if not p:
            return
        if p["is_case"] and p["case_group_id"]:
            # Mode 2 - shared pool: decrement the case group pool stock
            con.execute(
                "UPDATE price_groups SET pool_stock = MAX(0, pool_stock - ?) WHERE id = ?",
                (qty, p["case_group_id"])
            )
            con.execute(
                "INSERT INTO pool_stock_adjustments "
                "(case_group_id, qty_change, reason) VALUES (?, ?, 'Sale')",
                (p["case_group_id"], -qty)
            )
        elif p["is_case"] and p["case_product_id"]:
            # Mode 1 - linked: decrement the parent single product stock
            units = (p["case_qty"] or 1) * qty
            con.execute(
                "UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?",
                (units, p["case_product_id"])
            )
        else:
            # Plain single product
            con.execute(
                "UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?",
                (qty, product_id)
            )
        con.commit()


def adjust_stock(product_id: int, qty_change: int,
                 reason: str = "Restock", adjusted_by: int = None):
    """Manually adjust stock by qty_change (positive = add, negative = remove).
    Clamps at 0 for removals. Records in stock_adjustments for audit trail.
    """
    with _conn() as con:
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
            "INSERT INTO stock_adjustments (product_id, qty_change, reason, adjusted_by) "
            "VALUES (?, ?, ?, ?)",
            (product_id, qty_change, reason, adjusted_by)
        )
        con.commit()


def get_stock_adjustments(product_id: int, limit: int = 20) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT sa.*, p.name AS product_name "
            "FROM stock_adjustments sa JOIN products p ON p.id = sa.product_id "
            "WHERE sa.product_id = ? ORDER BY sa.adjusted_at DESC LIMIT ?",
            (product_id, limit)
        )]


def get_all_stock_adjustments(search: str = "", limit: int = 100) -> list[dict]:
    """Recent stock adjustments across all products, optionally filtered by product name."""
    q = """
        SELECT sa.*, p.name AS product_name
        FROM   stock_adjustments sa
        JOIN   products p ON p.id = sa.product_id
        WHERE  1=1
    """
    params: list = []
    if search:
        q += " AND LOWER(p.name) LIKE ?"
        params.append(f"%{search.lower()}%")
    q += " ORDER BY sa.adjusted_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_low_stock_products(threshold: int = 5) -> list[dict]:
    """Products at or below the given stock threshold, excluding case products."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            """SELECT p.*, g.name AS group_name
               FROM   products p
               LEFT   JOIN groups g ON g.id = p.group_id
               WHERE  p.stock <= ? AND p.is_case = 0
               ORDER  BY p.stock ASC, p.name""",
            (threshold,)
        )]


def increment_stock(product_id: int, qty: int):
    """Increment stock for a void/refund. Handles both case modes automatically.

    Mode 1: adds back case_qty x qty to the parent single product stock.
    Mode 2: adds back qty to the shared pool stock on the case group.
    """
    with _conn() as con:
        p = con.execute(
            "SELECT is_case, case_qty, case_product_id, case_group_id FROM products WHERE id = ?",
            (product_id,)
        ).fetchone()
        if not p:
            return
        if p["is_case"] and p["case_group_id"]:
            # Mode 2 - shared pool
            con.execute(
                "UPDATE price_groups SET pool_stock = pool_stock + ? WHERE id = ?",
                (qty, p["case_group_id"])
            )
            con.execute(
                "INSERT INTO pool_stock_adjustments "
                "(case_group_id, qty_change, reason) VALUES (?, ?, 'Void/Refund')",
                (p["case_group_id"], qty)
            )
        elif p["is_case"] and p["case_product_id"]:
            # Mode 1 - linked
            units = (p["case_qty"] or 1) * qty
            con.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (units, p["case_product_id"])
            )
        else:
            con.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (qty, product_id)
            )
        con.commit()


def count_products(search: str = "", group_id: int = None,
                   exclude_cases: bool = False) -> int:
    q = """
        SELECT COUNT(*) FROM products p
        LEFT JOIN price_groups ag ON ag.id = p.alias_group_id
        LEFT JOIN price_groups vg ON vg.id = p.variant_group_id
        WHERE 1=1
    """
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
