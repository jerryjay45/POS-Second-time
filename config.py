"""
Merchant POS Systems — Central Configuration
"""
import os
import sys

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Writable user-data root. Defaults to the app folder (portable / source runs).
# Packaged installs that live in a read-only location (Flatpak's /app) set
# MERCHANTPOS_HOME to a per-user writable directory.
USER_DIR   = os.environ.get("MERCHANTPOS_HOME") or BASE_DIR
if USER_DIR == BASE_DIR and getattr(sys, "frozen", False):
    # Frozen (PyInstaller) builds run from a bundle folder (_internal/ on
    # Linux, Program Files on Windows) that must not hold user data.
    if os.name == "nt":
        # The installer creates this folder with write access for all users
        USER_DIR = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "MerchantPOS")
    else:
        USER_DIR = os.path.join(
            os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
            "merchantpos")
DATA_DIR   = os.path.join(USER_DIR, "data")

# ── Database files ────────────────────────────────────────────────────────────
DB_PRODUCTS  = os.path.join(DATA_DIR, "products.db")
DB_USERS     = os.path.join(DATA_DIR, "users.db")
DB_CHECKOUT  = os.path.join(DATA_DIR, "checkout.db")
DB_CONFIG    = os.path.join(DATA_DIR, "config.db")

# ── External PostgreSQL (optional, set via Manager → PostgreSQL tab) ──────────
PG_HOST     = ""
PG_PORT     = 5432
PG_DATABASE = ""
PG_USER     = ""
PG_PASSWORD = ""
PG_ENABLED  = False

# ── App defaults (overridden by config.db at runtime) ─────────────────────────
APP_NAME    = "Merchant POS Systems"
APP_VERSION = "1.0.0"
GCT_RATE    = 0.165          # 16.5 %
CURRENCY    = "$"
RECEIPT_DIR = os.path.join(USER_DIR, "receipts")
LABEL_DIR   = os.path.join(USER_DIR, "labels")

# Quick-key slots (F1–F8); product_id or None
QUICK_KEY_SLOTS = 8

# Discount levels (qty thresholds are stored in config.db)
DISCOUNT_LEVELS = 2
