"""
core/db_users.py
Users database — roles, authentication, sessions.

Tables
------
users         — staff accounts (cashier / supervisor / manager)
sessions      — cashier login sessions (open / closed)
"""

import sqlite3
import threading
import hashlib
import secrets
from contextlib import contextmanager
from datetime import datetime
from config import DB_USERS

_local = threading.local()


@contextmanager
def _conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_USERS, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL is safe in WAL mode (no corruption; at worst the last commit is lost on
        # power cut) and avoids a forced disk sync on every commit — a big win on HDDs.
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield _local.conn
    except Exception:
        _local.conn.rollback()
        raise


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT    NOT NULL,
    username    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT  NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('cashier','supervisor','manager')),
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opened_by   INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_by   INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
    opened_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at   TEXT    DEFAULT NULL,
    total_sales REAL    NOT NULL DEFAULT 0.0,
    status      TEXT    NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','closed'))
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS session_cash_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK(kind IN ('float','count')),
    old_value   REAL    DEFAULT NULL,          -- NULL = there was no value before
    new_value   REAL    NOT NULL,
    changed_by  INTEGER DEFAULT NULL REFERENCES users(id) ON DELETE SET NULL,
    changed_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    note        TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_user  ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_cashlog_session ON session_cash_log(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        candidate = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        # Use secrets.compare_digest to prevent timing attacks
        return secrets.compare_digest(candidate, h)
    except (ValueError, AttributeError):
        return False


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    """Create tables. First manager account is created by the setup wizard."""
    with _conn() as con:
        con.executescript(SCHEMA)
        # Migrate existing sessions table — add columns if missing
        cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
        if "opened_by" not in cols:
            con.execute("ALTER TABLE sessions ADD COLUMN opened_by INTEGER DEFAULT NULL")
        if "closed_by" not in cols:
            con.execute("ALTER TABLE sessions ADD COLUMN closed_by INTEGER DEFAULT NULL")
        # Cash drawer: float_amount NULL = this session isn't tracked (feature off when it
        # opened); counted_cash NULL = "count pending".
        for col, ddl in (("float_amount", "REAL DEFAULT NULL"),
                         ("counted_cash", "REAL DEFAULT NULL"),
                         ("counted_by",   "INTEGER DEFAULT NULL"),
                         ("counted_at",   "TEXT DEFAULT NULL")):
            if col not in cols:
                con.execute(f"ALTER TABLE sessions ADD COLUMN {col} {ddl}")
        con.commit()


# ── Authentication ────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict | None:
    """
    Returns the user dict (without password_hash) on success, else None.
    Only active users may log in.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username.strip().upper(),)
        ).fetchone()
        if row and _verify_password(password.strip().upper(), row["password_hash"]):
            user = dict(row)
            del user["password_hash"]
            return user
    return None


def authenticate_supervisor_or_above(password: str) -> dict | None:
    """
    Check a password against every active supervisor or manager account
    and return the matching user dict, or None if it matches none of
    them. Used for re-authorising a sensitive action (void/refund, a
    manual drawer open) with just a password, without knowing in advance
    which supervisor/manager is present at the terminal.

    Same check used by ui/cashier/void_dialog.py's require_auth path —
    factored out here so new call sites don't duplicate the loop.
    """
    for u in get_users(role="supervisor") + get_users(role="manager"):
        if not u.get("is_active"):
            continue
        result = authenticate(u["username"], password)
        if result and result["id"] == u["id"]:
            return result
    return None


# ── Users CRUD ────────────────────────────────────────────────────────────────

def get_users(search: str = "", role: str = "") -> list[dict]:
    q = "SELECT id, full_name, username, role, is_active, created_at FROM users WHERE 1=1"
    params: list = []
    if search:
        q += " AND (full_name LIKE ? OR username LIKE ?)"
        s = f"%{search}%"
        params += [s, s]
    if role:
        q += " AND role = ?"
        params.append(role)
    q += " ORDER BY role, full_name COLLATE NOCASE"
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_user_by_id(user_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id, full_name, username, role, is_active, created_at "
            "FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def add_user(full_name: str, username: str, password: str,
             role: str, is_active: bool = True) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO users (full_name, username, password_hash, role, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (full_name.strip().upper(), username.strip().upper(),
             _hash_password(password.strip().upper()), role, int(is_active))
        )
        con.commit()
        return cur.lastrowid


def update_user(user_id: int, full_name: str = None, username: str = None,
                password: str = None, role: str = None,
                is_active: bool = None) -> bool:
    parts, params = [], []
    if full_name  is not None: parts.append("full_name = ?");      params.append(full_name.strip().upper())
    if username   is not None: parts.append("username = ?");       params.append(username.strip().upper())
    if password   is not None: parts.append("password_hash = ?");  params.append(_hash_password(password.strip().upper()))
    if role       is not None: parts.append("role = ?");           params.append(role)
    if is_active  is not None: parts.append("is_active = ?");      params.append(int(is_active))
    if not parts:
        return False
    parts.append("updated_at = datetime('now', 'localtime')")
    params.append(user_id)
    with _conn() as con:
        cur = con.execute(
            f"UPDATE users SET {', '.join(parts)} WHERE id = ?", params
        )
        con.commit()
        return cur.rowcount > 0


def count_active_managers(exclude_id: int | None = None) -> int:
    """Active manager accounts, optionally ignoring one user id."""
    q = "SELECT COUNT(*) FROM users WHERE role = 'manager' AND is_active = 1"
    params: tuple = ()
    if exclude_id is not None:
        q += " AND id != ?"
        params = (exclude_id,)
    with _conn() as con:
        return con.execute(q, params).fetchone()[0]


def delete_user(user_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM users WHERE id = ?", (user_id,))
        con.commit()
        return cur.rowcount > 0


# ── Sessions ──────────────────────────────────────────────────────────────────

def open_session(user_id: int, opened_by: int = None, float_amount: float = None) -> int:
    """Open a new cashier session. Returns session id.
    opened_by is the supervisor/manager who opened it (None = self-opened / auto-opened).

    Cash drawer: when tracking is on (Setup -> Cash Drawer) the session starts with
    `float_amount`, or with the standard float if none is given, and that amount is saved
    on the session so changing the standard later never alters old sessions. With tracking
    off the float stays NULL and nothing cash-related is recorded.
    """
    if float_amount is None:
        from core.db_config import get_bool, get_float
        if get_bool("cash_drawer_enabled", False):
            float_amount = max(0.0, get_float("cash_drawer_float", 0.0))
    elif float_amount < 0:
        raise ValueError("The float can't be negative.")
    if float_amount is not None:
        float_amount = round(float(float_amount), 2)
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO sessions (user_id, opened_by, float_amount) VALUES (?, ?, ?)",
            (user_id, opened_by, float_amount)
        )
        con.commit()
        return cur.lastrowid


def close_session(session_id: int, total_sales: float,
                  closed_by: int = None) -> bool:
    """Close an open session. closed_by is the supervisor/manager who closed it."""
    with _conn() as con:
        cur = con.execute(
            "UPDATE sessions SET status='closed', closed_at=datetime('now', 'localtime'), "
            "total_sales=?, closed_by=? WHERE id=? AND status='open'",
            (total_sales, closed_by, session_id)
        )
        con.commit()
        return cur.rowcount > 0


# ── Cash drawer: float and count ──────────────────────────────────────────────
# Fixed by role (no per-user switches): supervisors and managers may set a session's
# float and enter its first count; only a manager may correct a saved count. Every change
# is written to session_cash_log with who made it, so a correction is always visible.

_CASH_MAX = 10_000_000.0


def _clean_amount(value) -> float:
    try:
        v = round(float(value), 2)
    except (TypeError, ValueError):
        raise ValueError("Enter an amount.")
    if v != v or v < 0 or v > _CASH_MAX:        # NaN, negative or absurd
        raise ValueError("Enter an amount of 0 or more.")
    return v


def _role_of(con, user_id) -> str | None:
    row = con.execute("SELECT role FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
    return row["role"] if row else None


def set_session_float(session_id: int, amount: float, changed_by: int, note: str = "") -> float:
    """Set or change a session's opening float. Supervisor or manager only.
    Allowed while the session is open, and after it closes until its count is entered."""
    amount = _clean_amount(amount)
    with _conn() as con:
        if _role_of(con, changed_by) not in ("supervisor", "manager"):
            raise PermissionError("Only a supervisor or manager can change the float.")
        s = con.execute("SELECT status, float_amount, counted_cash FROM sessions WHERE id = ?",
                        (session_id,)).fetchone()
        if not s:
            raise ValueError("That session no longer exists.")
        if s["status"] != "open" and s["counted_cash"] is not None:
            raise ValueError("The cash has already been counted for this session, so its float is "
                             "locked. A manager can correct the count instead.")
        if s["float_amount"] is not None and round(s["float_amount"], 2) == amount:
            return amount                           # nothing changed: no log entry
        con.execute("UPDATE sessions SET float_amount = ? WHERE id = ?", (amount, session_id))
        con.execute("INSERT INTO session_cash_log (session_id, kind, old_value, new_value, changed_by, note) "
                    "VALUES (?, 'float', ?, ?, ?, ?)",
                    (session_id, s["float_amount"], amount, changed_by, (note or "").strip()[:120]))
        con.commit()
        return amount


def set_session_count(session_id: int, counted: float, changed_by: int, note: str = "") -> float:
    """Enter the counted cash for a CLOSED session. Supervisor or manager enters the first
    count; correcting a saved count is manager-only. The old value is kept in the log."""
    counted = _clean_amount(counted)
    with _conn() as con:
        role = _role_of(con, changed_by)
        if role not in ("supervisor", "manager"):
            raise PermissionError("Only a supervisor or manager can enter the cash count.")
        s = con.execute("SELECT status, float_amount, counted_cash FROM sessions WHERE id = ?",
                        (session_id,)).fetchone()
        if not s:
            raise ValueError("That session no longer exists.")
        if s["status"] != "closed":
            raise ValueError("Close the session before entering the cash count.")
        if s["float_amount"] is None:
            raise ValueError("This session has no float recorded, so there is no expected cash to compare with.")
        if s["counted_cash"] is not None and role != "manager":
            raise PermissionError("Only a manager can correct a saved count.")
        if s["counted_cash"] is not None and round(s["counted_cash"], 2) == counted:
            return counted
        con.execute("UPDATE sessions SET counted_cash = ?, counted_by = ?, "
                    "counted_at = datetime('now', 'localtime') WHERE id = ?",
                    (counted, changed_by, session_id))
        con.execute("INSERT INTO session_cash_log (session_id, kind, old_value, new_value, changed_by, note) "
                    "VALUES (?, 'count', ?, ?, ?, ?)",
                    (session_id, s["counted_cash"], counted, changed_by, (note or "").strip()[:120]))
        con.commit()
        return counted


def get_cash_log(session_id: int, limit: int = 20) -> list[dict]:
    """Float and count changes for a session, newest first, with the name of who made them."""
    with _conn() as con:
        rows = con.execute(
            """SELECT l.kind, l.old_value, l.new_value, l.changed_at, l.note,
                      u.full_name AS changed_by_name
               FROM session_cash_log l LEFT JOIN users u ON u.id = l.changed_by
               WHERE l.session_id = ? ORDER BY l.id DESC LIMIT ?""", (session_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_session_by_id(session_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def get_sessions(user_id: int = None, status: str = None) -> list[dict]:
    q = """
        SELECT s.*,
               u.full_name, u.username,
               ob.full_name AS opened_by_name,
               cb.full_name AS closed_by_name
        FROM   sessions s
        JOIN   users u  ON u.id  = s.user_id
        LEFT JOIN users ob ON ob.id = s.opened_by
        LEFT JOIN users cb ON cb.id = s.closed_by
        WHERE  1=1
    """
    params: list = []
    if user_id is not None:
        q += " AND s.user_id = ?"
        params.append(user_id)
    if status:
        q += " AND s.status = ?"
        params.append(status)
    q += " ORDER BY s.opened_at DESC"
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_open_session(user_id: int) -> dict | None:
    """Return the currently open session for a cashier, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM sessions WHERE user_id=? AND status='open' "
            "ORDER BY opened_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def has_open_session(user_id: int) -> bool:
    """Return True if the cashier has an open session."""
    return get_open_session(user_id) is not None


def add_session_sales(session_id: int, amount: float):
    """Increment running total for an open session."""
    with _conn() as con:
        con.execute(
            "UPDATE sessions SET total_sales = total_sales + ? WHERE id = ?",
            (amount, session_id)
        )
        con.commit()


def get_sessions_page(user_id: int, limit: int = 30, offset: int = 0,
                      date_from: str = "", date_to: str = "",
                      number: str = "") -> list[dict]:
    """One cashier's sessions, newest first, a page at a time.

    date_from/date_to are 'YYYY-MM-DD' (inclusive). `number` matches the
    session id as typed ('12', '#0012'). Used by the Reports history popup so
    the dashboard never loads every session a cashier has ever had.
    """
    q = "SELECT * FROM sessions WHERE user_id = ?"
    params: list = [user_id]
    if date_from:
        q += " AND opened_at >= ?";               params.append(date_from)
    if date_to:
        q += " AND opened_at < date(?, '+1 day')"; params.append(date_to)
    number = number.lstrip("#").strip()
    if number.isdigit():
        q += " AND CAST(id AS TEXT) LIKE ?";      params.append(f"%{int(number)}%")
    q += " ORDER BY opened_at DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _conn() as con:
        return [dict(r) for r in con.execute(q, params)]


def get_latest_session(user_id: int) -> dict | None:
    """The open session if there is one, otherwise the most recent."""
    return get_open_session(user_id) or next(iter(get_sessions_page(user_id, 1)), None)
