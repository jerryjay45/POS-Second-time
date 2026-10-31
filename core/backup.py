"""
core/backup.py — backups for Merchant POS Systems.

A backup is ONE zip holding a consistent snapshot of the four databases
(taken with SQLite's online-backup API, so it is safe while a till is mid-sale),
optionally the receipts/ and labels/ folders, and a manifest with SHA-256
checksums.  Every archive is verified after it is written and again after it
is copied to each destination.

No UI code lives here: the Backup tab, the scheduler in main.py and the import
tab all call into this module.

Settings and history are kept in JSON files in <USER_DIR>/backup/, NOT in the
databases, so restoring an old backup can never roll back the destination list
or erase the backup history.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta

import config

FORMAT_VERSION = 1

# Order matters: sales (checkout) are copied first.  They point at products and
# users, so a product added mid-backup can never leave a sale pointing at
# something the backup doesn't contain.
DB_ORDER = ("checkout", "products", "users", "config")

REGULAR_KINDS = ("daily", "logout", "manual")        # rotated by day / week
SPECIAL_KINDS = ("pre-import", "pre-restore")        # kept separately
AUTO_KINDS    = ("daily", "logout")                  # skipped when nothing changed

LOG_LIMIT = 200

_NAME_RE = re.compile(
    r"^MerchantPOS_(?P<tid>[A-Za-z0-9-]+)_(?P<ts>\d{8}-\d{6})_(?P<kind>[a-z-]+)\.zip$"
)

DEFAULT_SETTINGS = {
    "include_files":     True,     # receipts/ and labels/ folders
    "daily_enabled":     True,
    "daily_time":        "21:00",
    "on_manager_logout": True,
    "before_import":     True,
    "keep_daily":        14,
    "keep_weekly":       4,
    "keep_special":      5,
}

_run_lock = threading.Lock()      # one backup or restore at a time
_file_lock = threading.Lock()     # settings / log files


class BackupError(Exception):
    """A backup or restore step failed; the message is safe to show the user."""


# ── paths ────────────────────────────────────────────────────────────────────

def _db_path(name: str) -> str:
    return {"checkout": config.DB_CHECKOUT, "products": config.DB_PRODUCTS,
            "users": config.DB_USERS, "config": config.DB_CONFIG}[name]


def backup_dir() -> str:
    return os.path.join(config.USER_DIR, "backup")


def documents_dir() -> str:
    return os.environ.get("XDG_DOCUMENTS_DIR") or os.path.join(os.path.expanduser("~"), "Documents")


def default_local_path() -> str:
    return os.path.join(documents_dir(), "MerchantPOS Backups")


def _atomic_write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ── settings & log ───────────────────────────────────────────────────────────

def load_settings() -> dict:
    raw = _read_json(os.path.join(backup_dir(), "settings.json"), {})
    s = {**DEFAULT_SETTINGS, **{k: v for k, v in raw.items() if k in DEFAULT_SETTINGS}}
    if isinstance(raw.get("destinations"), list):
        s["destinations"] = [d for d in raw["destinations"] if isinstance(d, dict) and d.get("path")]
    else:   # never configured: start with a local folder so backups work out of the box
        s["destinations"] = [{"id": "local", "label": "This computer",
                              "path": default_local_path(), "enabled": True}]
    return s


def save_settings(settings: dict) -> None:
    clean = {k: settings[k] for k in DEFAULT_SETTINGS if k in settings}
    clean["destinations"] = [
        {"id": str(d.get("id") or f"d{i}"), "label": str(d.get("label") or d["path"]),
         "path": str(d["path"]), "enabled": bool(d.get("enabled", True))}
        for i, d in enumerate(settings.get("destinations", [])) if d.get("path")
    ]
    with _file_lock:
        _atomic_write_json(os.path.join(backup_dir(), "settings.json"), clean)


def read_log() -> list[dict]:
    """History, newest first."""
    with _file_lock:
        entries = _read_json(os.path.join(backup_dir(), "log.json"), [])
    return list(reversed(entries)) if isinstance(entries, list) else []


def _append_log(entry: dict) -> None:
    path = os.path.join(backup_dir(), "log.json")
    with _file_lock:
        entries = _read_json(path, [])
        if not isinstance(entries, list):
            entries = []
        entries.append(entry)
        _atomic_write_json(path, entries[-LOG_LIMIT:])


def last_success() -> dict | None:
    return next((e for e in read_log() if e.get("ok") and not e.get("skipped")), None)


# ── small helpers ────────────────────────────────────────────────────────────

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _terminal_id() -> str:
    tid = "01"
    try:                                       # plain read; avoids a connection per thread
        con = sqlite3.connect(config.DB_CONFIG, timeout=10)
        try:
            row = con.execute("SELECT value FROM settings WHERE key='terminal_id'").fetchone()
            if row and row[0]:
                tid = row[0]
        finally:
            con.close()
    except sqlite3.Error:
        pass
    return re.sub(r"[^A-Za-z0-9]", "", tid) or "01"


def fingerprint() -> str:
    """Cheap 'has anything changed?' value from file sizes and mtimes."""
    h = hashlib.sha1()
    for name in DB_ORDER:
        for suffix in ("", "-wal"):
            try:
                st = os.stat(_db_path(name) + suffix)
                h.update(f"{name}{suffix}:{st.st_size}:{st.st_mtime_ns};".encode())
            except OSError:
                h.update(f"{name}{suffix}:-;".encode())
    return h.hexdigest()


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3]) or (0,)


def _integrity_ok(db_file: str) -> bool:
    con = sqlite3.connect(db_file)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def _walk_files(folder: str, arc_prefix: str):
    if not os.path.isdir(folder):
        return
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            yield full, f"{arc_prefix}/{rel}"


# ── archive building / verifying ─────────────────────────────────────────────

def _snapshot_databases(tmpdir: str) -> dict[str, str]:
    out = {}
    for name in DB_ORDER:
        src_path = _db_path(name)
        if not os.path.exists(src_path):
            raise BackupError(f"{os.path.basename(src_path)} was not found.")
        dst_path = os.path.join(tmpdir, f"{name}.db")
        src = sqlite3.connect(src_path, timeout=30)
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)                     # consistent copy, safe with writers active
            dst.execute("PRAGMA journal_mode=DELETE")   # one self-contained file
        finally:
            dst.close()
            src.close()
        if not _integrity_ok(dst_path):
            raise BackupError(f"The copy of {name}.db failed SQLite's integrity check.")
        out[name] = dst_path
    return out


def _build_archive(zip_path: str, snapshots: dict[str, str], kind: str, tid: str,
                   include_files: bool) -> None:
    files: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        def add(full, arc):
            zf.write(full, arc)
            files[arc] = {"sha256": _sha256(full), "size": os.path.getsize(full)}
        for name in DB_ORDER:
            add(snapshots[name], f"databases/{name}.db")
        if include_files:
            for folder, prefix in ((config.RECEIPT_DIR, "receipts"), (config.LABEL_DIR, "labels")):
                for full, arc in _walk_files(folder, prefix):
                    try:
                        add(full, arc)
                    except OSError:
                        pass                    # a file vanished mid-backup: skip it
        manifest = {"format": FORMAT_VERSION, "app": config.APP_NAME,
                    "app_version": config.APP_VERSION, "terminal": tid, "kind": kind,
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "files": files}
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))


def verify_archive(path: str) -> dict:
    """Check a backup zip end to end. Returns its manifest or raises BackupError."""
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                raise BackupError(f"The backup is damaged ({bad}).")
            try:
                manifest = json.loads(zf.read("manifest.json"))
            except (KeyError, ValueError):
                raise BackupError("This is not a Merchant POS backup (no manifest).")
            if manifest.get("format", 0) > FORMAT_VERSION:
                raise BackupError("This backup was made by a newer version of the program.")
            files = manifest.get("files", {})
            for name in DB_ORDER:
                if f"databases/{name}.db" not in files:
                    raise BackupError(f"The backup does not contain {name}.db.")
            with tempfile.TemporaryDirectory(prefix="mpos-verify-") as tmp:
                for arc, meta in files.items():
                    h = hashlib.sha256()
                    with zf.open(arc) as member:
                        target = None
                        if arc.startswith("databases/"):
                            target = os.path.join(tmp, os.path.basename(arc))
                            out = open(target, "wb")
                        else:
                            out = None
                        try:
                            for chunk in iter(lambda: member.read(1 << 20), b""):
                                h.update(chunk)
                                if out:
                                    out.write(chunk)
                        finally:
                            if out:
                                out.close()
                    if h.hexdigest() != meta["sha256"]:
                        raise BackupError(f"Checksum mismatch in {arc}; the backup is damaged.")
                    if target and not _integrity_ok(target):
                        raise BackupError(f"{os.path.basename(arc)} in the backup is corrupt.")
            return manifest
    except zipfile.BadZipFile:
        raise BackupError("The file is not a valid zip archive.")
    except OSError as e:
        raise BackupError(f"Could not read the backup: {e}")


# ── destinations ─────────────────────────────────────────────────────────────

def test_destination(path: str) -> tuple[bool, str]:
    """Write and delete a small file; report free space."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".mpos-write-test-{os.getpid()}")
        with open(probe, "wb") as f:
            f.write(b"ok")
        os.remove(probe)
        free_mb = shutil.disk_usage(path).free // (1024 * 1024)
    except OSError as e:
        return False, f"Cannot write to this location: {e}"
    if free_mb < 200:
        return True, f"Works, but only {free_mb} MB free."
    return True, f"Works ({free_mb:,} MB free)."


def _copy_verified(src: str, dest_dir: str, fname: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, fname)
    part = os.path.join(dest_dir, f".{fname}.partial")
    try:
        shutil.copyfile(src, part)
        if _sha256(part) != _sha256(src):
            raise BackupError("The copy did not match the original (checksum differs).")
        os.replace(part, final)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
    return final


# ── listing & retention ──────────────────────────────────────────────────────

def parse_backup_name(name: str) -> dict | None:
    m = _NAME_RE.match(name)
    if not m:
        return None
    try:
        ts = datetime.strptime(m["ts"], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return {"name": name, "tid": m["tid"], "ts": ts, "kind": m["kind"]}


def list_backups(directories: list[tuple[str, str]] | None = None) -> list[dict]:
    """Backups in each (label, path) directory, newest first.
    Defaults to the enabled destinations."""
    if directories is None:
        directories = [(d["label"], d["path"]) for d in load_settings()["destinations"]
                       if d.get("enabled", True)]
    found = []
    for label, path in directories:
        try:
            names = os.listdir(path)
        except OSError:
            continue
        for n in names:
            info = parse_backup_name(n)
            if info:
                full = os.path.join(path, n)
                try:
                    info.update(path=full, destination=label, size=os.path.getsize(full))
                except OSError:
                    continue
                found.append(info)
    found.sort(key=lambda b: b["ts"], reverse=True)
    return found


def prune_destination(path: str, tid: str, settings: dict | None = None,
                      now: datetime | None = None, protect: str | None = None) -> list[str]:
    """Apply retention in one folder, for this terminal's backups only.
    `protect` is a file name that must never be deleted (the backup just made).
    Returns the file names deleted."""
    s = settings or load_settings()
    now = now or datetime.now()
    # Newest first; the name breaks ties between backups made in the same second.
    mine = sorted((b for b in list_backups([("", path)]) if b["tid"] == tid),
                  key=lambda b: (b["ts"], b["name"]), reverse=True)
    regular = [b for b in mine if b["kind"] in REGULAR_KINDS]
    special = [b for b in mine if b["kind"] in SPECIAL_KINDS]
    keep: set[str] = set()
    if protect:
        keep.update(b["path"] for b in mine if b["name"] == protect)

    if regular:
        keep.add(regular[0]["path"])                                # newest is never pruned
    days: list = []
    for b in regular:                                               # newest backup of each recent day
        d = b["ts"].date()
        if d not in days:
            days.append(d)
            if len(days) <= int(s["keep_daily"]):
                keep.add(b["path"])
    recent_days = set(days[: int(s["keep_daily"])])
    weeks: list = []
    for b in regular:                                               # then one per older week
        if b["ts"].date() in recent_days:
            continue
        wk = tuple(b["ts"].isocalendar())[:2]
        if wk not in weeks:
            weeks.append(wk)
            if len(weeks) <= int(s["keep_weekly"]):
                keep.add(b["path"])
    for i, b in enumerate(special):
        if i < int(s["keep_special"]) or b["ts"] > now - timedelta(days=30):
            keep.add(b["path"])

    deleted = []
    for b in mine:
        if b["path"] not in keep:
            try:
                os.remove(b["path"])
                deleted.append(b["name"])
            except OSError:
                pass
    return deleted


# ── create ───────────────────────────────────────────────────────────────────

def create_backup(kind: str = "manual", wait: bool = False) -> dict:
    """Make a backup now and copy it to every enabled destination.

    Returns a result dict: ok, skipped, busy, error, file, destinations.
    `wait=True` queues behind a backup already running (used before imports);
    otherwise a busy engine returns immediately with busy=True.
    """
    if not _run_lock.acquire(timeout=120 if wait else 0):
        return {"ok": False, "busy": True, "error": "Another backup is already running."}
    tmpdir = None
    started = datetime.now()
    entry = {"ts": started.isoformat(timespec="seconds"), "kind": kind, "ok": False}
    try:
        settings = load_settings()
        dests = [d for d in settings["destinations"] if d.get("enabled", True)]
        if not dests:
            raise BackupError("No backup destination is set up.")

        fp = fingerprint()
        if kind in AUTO_KINDS:
            last = last_success()
            if last and last.get("fingerprint") == fp:
                entry.update(ok=True, skipped=True, fingerprint=fp)
                if kind == "daily":              # so the scheduler knows today's check happened
                    _append_log(entry)
                return {"ok": True, "skipped": True}
        entry["fingerprint"] = fp

        tid = _terminal_id()
        fname = f"MerchantPOS_{tid}_{started:%Y%m%d-%H%M%S}_{kind}.zip"
        tmpdir = tempfile.mkdtemp(prefix="mpos-backup-")
        snaps = _snapshot_databases(tmpdir)
        zip_path = os.path.join(tmpdir, fname)
        _build_archive(zip_path, snaps, kind, tid, bool(settings["include_files"]))
        verify_archive(zip_path)

        results = []
        for d in dests:
            r = {"label": d["label"], "path": d["path"], "ok": False}
            try:
                _copy_verified(zip_path, d["path"], fname)
                r["ok"] = True
                try:
                    r["pruned"] = len(prune_destination(d["path"], tid, settings, started, protect=fname))
                except Exception:
                    pass
            except (OSError, BackupError) as e:
                r["error"] = str(e)
            results.append(r)

        good = [r for r in results if r["ok"]]
        entry.update(ok=bool(good), file=fname, size=os.path.getsize(zip_path),
                     destinations=results)
        if not good:
            entry["error"] = "Could not save the backup to any destination."
        _append_log(entry)
        return {"ok": bool(good), "file": fname, "destinations": results,
                "error": entry.get("error"), "partial": bool(good) and len(good) < len(results)}
    except (BackupError, OSError, sqlite3.Error) as e:
        entry["error"] = str(e)
        _append_log(entry)
        return {"ok": False, "error": str(e)}
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        _run_lock.release()


def run_async(kind: str, on_done=None) -> threading.Thread | None:
    """Run create_backup on a background thread (never blocks the UI)."""
    if _run_lock.locked():
        return None

    def work():
        res = create_backup(kind)
        if on_done:
            try:
                on_done(res)
            except Exception:
                pass
    t = threading.Thread(target=work, name=f"backup-{kind}", daemon=True)
    t.start()
    return t


def is_running() -> bool:
    return _run_lock.locked()


# ── scheduling ───────────────────────────────────────────────────────────────

def daily_due(now: datetime | None = None, settings: dict | None = None,
              log: list[dict] | None = None) -> bool:
    """True when today's scheduled backup should run now.

    Also covers a till that was off at the scheduled time: the first check after
    start-up fires it.  A failed attempt is retried at most every 30 minutes.
    """
    now = now or datetime.now()
    s = settings or load_settings()
    if not s["daily_enabled"] or not any(d.get("enabled", True) for d in s["destinations"]):
        return False
    try:
        hh, mm = (int(x) for x in str(s["daily_time"]).split(":")[:2])
    except ValueError:
        hh, mm = 21, 0
    if now < now.replace(hour=hh, minute=mm, second=0, microsecond=0):
        return False
    today = [e for e in (log if log is not None else read_log())
             if e.get("kind") == "daily" and str(e.get("ts", ""))[:10] == now.date().isoformat()]
    if any(e.get("ok") for e in today):
        return False
    if today:                                   # only failures so far: back off
        try:
            last = datetime.fromisoformat(today[0]["ts"])       # log is newest first
            if now - last < timedelta(minutes=30):
                return False
        except (KeyError, ValueError):
            pass
    return True


def newest_backup_age_days(now: datetime | None = None) -> float | None:
    last = last_success()
    if not last:
        return None
    try:
        return ((now or datetime.now()) - datetime.fromisoformat(last["ts"])).total_seconds() / 86400
    except (KeyError, ValueError):
        return None


# ── restore ──────────────────────────────────────────────────────────────────

def release_connections() -> None:
    """Close this thread's open database connections so the files can be replaced.
    The db_* modules reopen them on demand."""
    from core import db_checkout, db_config, db_products, db_users
    for mod in (db_checkout, db_config, db_products, db_users):
        loc = getattr(mod, "_local", None)
        conn = getattr(loc, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            loc.conn = None


def _safe_target(base: str, arc: str) -> str | None:
    target = os.path.normpath(os.path.join(base, *arc.split("/")[1:]))
    return target if target.startswith(os.path.normpath(base) + os.sep) else None


def restore_backup(path: str) -> dict:
    """Replace the databases with those in `path`.

    1. verifies the archive, 2. makes a 'pre-restore' safety backup, 3. extracts
    everything to temporary files, 4. swaps the database files in, 5. merges
    receipts/labels (never overwrites or deletes an existing file).
    The program must be restarted afterwards.
    """
    manifest = verify_archive(path)
    if _version_tuple(manifest.get("app_version", "0")) > _version_tuple(config.APP_VERSION):
        raise BackupError(f"This backup was made by a newer version ({manifest['app_version']}) "
                          f"than this program ({config.APP_VERSION}).")

    safety = create_backup("pre-restore", wait=True)
    if not safety.get("ok"):
        raise BackupError("Could not make a safety backup of the current data first: "
                          + str(safety.get("error", "unknown error")) + "\nNothing was changed.")

    if not _run_lock.acquire(timeout=120):
        raise BackupError("A backup is running; try again in a moment. Nothing was changed.")
    staged: list[tuple[str, str]] = []
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            for name in DB_ORDER:                                  # stage first, swap later
                tmp = _db_path(name) + ".restoring"
                with zf.open(f"databases/{name}.db") as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                staged.append((tmp, _db_path(name)))

            release_connections()
            try:
                for tmp, final in staged:
                    for suffix in ("-wal", "-shm"):                # stale journal of the old data
                        try:
                            os.remove(final + suffix)
                        except FileNotFoundError:
                            pass
                    os.replace(tmp, final)
            except OSError as e:
                raise BackupError(
                    f"Could not replace {os.path.basename(final)}: {e}\n"
                    f"The restore is incomplete. Your previous data is in the safety backup "
                    f"'{safety.get('file')}'.")

            merged = 0
            for arc in manifest["files"]:
                for prefix, folder in (("receipts/", config.RECEIPT_DIR), ("labels/", config.LABEL_DIR)):
                    if arc.startswith(prefix):
                        target = _safe_target(folder, arc)
                        if target and not os.path.exists(target):
                            os.makedirs(os.path.dirname(target), exist_ok=True)
                            with zf.open(arc) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            merged += 1
        return {"ok": True, "safety_backup": safety.get("file"), "restored_from": manifest.get("created"),
                "files_merged": merged}
    finally:
        for tmp, _final in staged:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        _run_lock.release()
