"""
core/__init__.py
Initialises all four databases on import.
"""
from core.db_products import init_db as _init_products
from core.db_users    import init_db as _init_users
from core.db_checkout import init_db as _init_checkout
from core.db_config   import init_db as _init_config


def init_all_databases():
    """Call once at application startup."""
    _init_products()
    _init_users()
    _init_checkout()
    _init_config()
