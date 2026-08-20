"""
core/db_config.py
Config database — business settings, GCT rate, discount levels,
quick keys (F1–F8), printer config, and PostgreSQL connection info.

Tables
------
business      — single-row business info
settings      — key/value store for all other config
quick_keys    — F1–F8 product assignments
"""

import sqlite3
import threading
from contextlib import contextmanager
from config import DB_CONFIG

_local = threading.local()


@contextmanager
def _conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_CONFIG, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield _local.conn
    except Exception:
        _local.conn.rollback()
        raise


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS business (
    id              INTEGER PRIMARY KEY CHECK(id = 1),  -- singleton
    name            TEXT    NOT NULL DEFAULT 'My Business',
    address         TEXT    NOT NULL DEFAULT '',
    phone           TEXT    NOT NULL DEFAULT '',
    email           TEXT    NOT NULL DEFAULT '',
    tax_id          TEXT    NOT NULL DEFAULT '',
    receipt_footer  TEXT    NOT NULL DEFAULT 'Thank you for your business!',
    logo_path       TEXT    DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quick_keys (
    slot        INTEGER PRIMARY KEY,   -- 1–8  (F1=1 … F8=8)
    product_id  INTEGER DEFAULT NULL,
    product_name TEXT   DEFAULT NULL,
    product_price REAL  DEFAULT NULL
);
"""

# ── Default settings seeded on first run ──────────────────────────────────────
_DEFAULTS = {
    # Tax
    "gct_rate":              "0.165",      # 16.5 %
    "gct_enabled":           "1",

    # Discount level thresholds (qty) and prices — set per product, but
    # the *percentage* fallback lives here for global discount config.
    "discount_level1_pct":   "0.05",       # 5 % off at level-1 qty
    "discount_level2_pct":   "0.10",       # 10 % off at level-2 qty

    # Quick-amount buttons in checkout dialog (comma-separated)
    "checkout_quick_amounts": "2,5,10,20,50,100",

    # Printer — single receipt printer, used for all receipt/void/refund/
    # session printing. See utils/printer_capabilities.py for the paper
    # width → column table and utils/thermal_printer.py for print modes.
    "receipt_printer_name":   "",          # blank = OS default printer
    "receipt_printer_mode":   "raw",       # "raw" (dot matrix / thermal passthrough) or "raster" (QPrinter graphics)
    "receipt_paper_width_mm": "76",        # physical paper width in mm — drives column count
    "receipt_copies":         "1",
    "label_printer_name":     "",
    "receipt_printer_escpos": "0",         # "1" = send real ESC/POS commands (bold headers/totals, paper cut) instead of plain ASCII — raw mode only, needs an ESC/POS-capable printer
    "cash_drawer_kick_on_cash_sale": "0",  # "1" = send the cash-drawer-open command after printing a cash/split-tender sale receipt — ESC/POS mode only

    # PostgreSQL external DB (mirrors config.py but persisted here)
    "pg_enabled":            "0",
    "pg_host":               "",
    "pg_port":               "5432",
    "pg_database":           "",
    "pg_user":               "",
    "pg_password":           "",

    # Case pricing
    "case_profit_pct":       "0.10",       # 10 % markup over cost for case products

    # UI
    "currency_symbol":       "$",
    "terminal_id":           "01",

    # Cashier behaviour
    "allow_cart_qty_edit":   "0",          # allow double-click qty edit in cart
    "low_stock_warning":     "0",          # warn cashier when stock is low
    "low_stock_threshold":   "5",          # qty at or below which warning shows
    "session_gate":          "0",          # require supervisor to open session manually
    "stock_tracking":        "0",          # track and decrement stock on sales
}


def init_db():
    """Create tables, seed defaults, ensure quick_key slots exist."""
    with _conn() as con:
        con.executescript(SCHEMA)

        # Seed business row
        con.execute(
            "INSERT OR IGNORE INTO business (id) VALUES (1)"
        )

        # Seed settings defaults
        con.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            list(_DEFAULTS.items())
        )

        # Seed 8 empty quick-key slots
        con.executemany(
            "INSERT OR IGNORE INTO quick_keys (slot) VALUES (?)",
            [(i,) for i in range(1, 9)]
        )

        con.commit()


# ── Business info ─────────────────────────────────────────────────────────────

def get_business() -> dict:
    with _conn() as con:
        row = con.execute("SELECT * FROM business WHERE id = 1").fetchone()
        return dict(row) if row else {}


def update_business(**fields) -> bool:
    if not fields:
        return False
    # Uppercase all text fields except email, website, and numeric fields
    _skip_upper = {"email", "website", "gct_rate"}
    fields = {
        k: v.strip().upper() if isinstance(v, str) and k not in _skip_upper else v
        for k, v in fields.items()
    }
    parts = [f"{k} = ?" for k in fields]
    params = list(fields.values())
    with _conn() as con:
        cur = con.execute(
            f"UPDATE business SET {', '.join(parts)} WHERE id = 1", params
        )
        con.commit()
        return cur.rowcount > 0


# ── Generic settings ──────────────────────────────────────────────────────────

def get(key: str, default: str = "") -> str:
    with _conn() as con:
        row = con.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get(key, str(default)))
    except ValueError:
        return default


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get(key, str(default)))
    except ValueError:
        return default


def get_bool(key: str, default: bool = False) -> bool:
    return get(key, "1" if default else "0") == "1"


def set(key: str, value: str):
    with _conn() as con:
        con.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value))
        )
        con.commit()


def set_many(pairs: dict):
    with _conn() as con:
        con.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, str(v)) for k, v in pairs.items()]
        )
        con.commit()


def get_all() -> dict:
    with _conn() as con:
        return {r["key"]: r["value"]
                for r in con.execute("SELECT key, value FROM settings")}


# ── GCT / Discount helpers ────────────────────────────────────────────────────

def gct_rate() -> float:
    return get_float("gct_rate", 0.165)


def discount_pct(level: int) -> float:
    """Return discount percentage for level 1 or 2."""
    key = f"discount_level{level}_pct"
    return get_float(key, 0.0)


def checkout_quick_amounts() -> list[float]:
    raw = get("checkout_quick_amounts", "2,5,10,20,50,100")
    try:
        return [float(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return [2, 5, 10, 20, 50, 100]


# ── Quick Keys (F1–F8) ────────────────────────────────────────────────────────

def get_quick_keys() -> list[dict]:
    """Return all 8 slots ordered by slot number."""
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM quick_keys ORDER BY slot"
        )]


def set_quick_key(slot: int, product_id: int = None,
                  product_name: str = None, product_price: float = None):
    """Assign or clear (pass None) a quick-key slot."""
    with _conn() as con:
        con.execute(
            "UPDATE quick_keys SET product_id=?, product_name=?, product_price=? "
            "WHERE slot=?",
            (product_id, product_name, product_price, slot)
        )
        con.commit()


def save_quick_keys(assignments: list[dict]):
    """
    Bulk-save all 8 slots.
    assignments: list of dicts with keys slot, product_id, product_name, product_price
    """
    with _conn() as con:
        for a in assignments:
            con.execute(
                "UPDATE quick_keys SET product_id=?, product_name=?, product_price=? "
                "WHERE slot=?",
                (a.get("product_id"), a.get("product_name"),
                 a.get("product_price"), a["slot"])
            )
        con.commit()


# ── PostgreSQL settings ───────────────────────────────────────────────────────

def get_pg_config() -> dict:
    keys = ["pg_enabled", "pg_host", "pg_port", "pg_database", "pg_user", "pg_password"]
    with _conn() as con:
        rows = con.execute(
            f"SELECT key, value FROM settings WHERE key IN ({','.join('?'*len(keys))})",
            keys
        ).fetchall()
    cfg = {r["key"]: r["value"] for r in rows}
    return {
        "enabled":  cfg.get("pg_enabled", "0") == "1",
        "host":     cfg.get("pg_host", ""),
        "port":     int(cfg.get("pg_port", "5432")),
        "database": cfg.get("pg_database", ""),
        "user":     cfg.get("pg_user", ""),
        "password": cfg.get("pg_password", ""),
    }


def save_pg_config(enabled: bool, host: str, port: int,
                   database: str, user: str, password: str):
    set_many({
        "pg_enabled":  "1" if enabled else "0",
        "pg_host":     host,
        "pg_port":     str(port),
        "pg_database": database,
        "pg_user":     user,
        "pg_password": password,
    })
