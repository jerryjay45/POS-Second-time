"""
Merchant POS Systems — Central Configuration
"""
import os

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

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
RECEIPT_DIR = os.path.join(BASE_DIR, "receipts")
LABEL_DIR   = os.path.join(BASE_DIR, "labels")

# Quick-key slots (F1–F8); product_id or None
QUICK_KEY_SLOTS = 8

# Discount levels (qty thresholds are stored in config.db)
DISCOUNT_LEVELS = 2
