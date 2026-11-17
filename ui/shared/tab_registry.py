"""
ui/shared/tab_registry.py — the one list of what the Supervisor and Manager
windows show, how it is grouped, and who may open each page.

Both windows build their tabs from AREAS, filtered by role, so moving a page to
another area (or sharing it with supervisors) is a one-line change here instead
of an edit in two windows.

  AREA  = a top-level tab (Sales, Inventory, ...)
  PAGE  = a sub-tab inside an area (an area with a single visible page is shown
          directly, without a sub-tab row)

Access is fixed by role (cashier < supervisor < manager); there are no
per-user switches.  Pages are still built lazily (ui/shared/lazy_tabs.py): an
area is built the first time it is opened, and each page inside it the first
time that sub-tab is opened.

Builders are the window's own `_build_*_tab` methods, named here as strings, so
this module imports no UI code and the windows keep their existing page code.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

from PyQt6.QtWidgets import QTabWidget

ROLE_RANK = {"cashier": 0, "supervisor": 1, "manager": 2}


class Page(NamedTuple):
    key: str                                   # stable id: window._lazy.page(key)
    title: str
    builder: str                               # method name on the window
    refresher: Callable | None = None          # called with the window when you come back
    min_role: str = "supervisor"


class Area(NamedTuple):
    key: str
    title: str
    pages: tuple[Page, ...]


# Refreshers reload table data only, never the user's input (see lazy_tabs.py).
# Forms that hold unsaved edits (Quick Keys, Business, Tax, Permissions, Pickup, Import ...) have none.
AREAS: tuple[Area, ...] = (
    Area("sales", "💰  Sales", (
        Page("reports", "📊  Reports", "_build_reports_tab",
             lambda w: w._rpt_refresh_on_show()),
        Page("transactions", "🧾  Transactions", "_build_transactions_tab",
             lambda w: w._tx_load(w._tx_pg_search, w._tx_pg_status)),
        Page("void", "↩  Void / Refund", "_build_void_tab",
             lambda w: w._vr_refresh_on_show()),
    )),
    Area("inventory", "📦  Inventory", (
        Page("products", "📦  Products", "_build_products_tab",
             lambda w: w._load_products(w._pg_search)),
        Page("stock", "📊  Stock", "_build_stock_tab",
             lambda w: w._lazy.page("stock")._refresh_all()),
        Page("pricetags", "🏷  Price Tags", "_build_price_tag_tab",
             lambda w: w._lazy.page("pricetags")._load_table()),
        Page("quickkeys", "⌨  Quick Keys", "_build_quickkeys_tab"),
        # "&&": a single "&" in a Qt tab title is a keyboard-shortcut marker and gets swallowed.
        Page("groups", "📂  Groups && Discounts", "_build_groups_panel_page", None, "manager"),
        Page("stocksettings", "⚙  Stock Settings", "_build_stock_settings_tab", None, "manager"),
    )),
    Area("printing", "🖨  Printing", (
        # Printer Setup is the simple page (supervisor + manager); the two "advanced" pages
        # write the same settings, so each reloads on return unless it has unsaved edits.
        Page("printersetup", "🖨  Printer Setup", "_build_printer_setup_tab",
             lambda w: w._lazy.page("printersetup").reload_if_clean()),
        Page("receipt", "🧾  Receipt (advanced)", "_build_receipt_tab",
             lambda w: w._lazy.page("receipt").reload_if_clean(), "manager"),
        Page("pickup", "🍽  Pickup (advanced)", "_build_pickup_tab",
             lambda w: w._lazy.page("pickup").reload_if_clean(), "manager"),
    )),
    Area("data", "💾  Data", (
        # Supervisors get the limited view (status, history, Back up now, Test).
        Page("backup", "💾  Backup", "_build_backup_tab",
             lambda w: w._lazy.page("backup").refresh()),
        Page("import", "📥  Import", "_build_dbf_import_tab", None, "manager"),
        Page("postgres", "🗄  PostgreSQL", "_build_postgres_tab", None, "manager"),
    )),
    Area("setup", "🔧  Setup", (
        Page("users", "👥  Users", "_build_users_tab",
             lambda w: w._usr_refresh_on_show(), "manager"),
        Page("permissions", "🔒  Permissions", "_build_permissions_tab", None, "manager"),
        Page("business", "🏢  Business", "_build_business_tab", None, "manager"),
        Page("tax", "💲  Tax && Currency", "_build_tax_tab", None, "manager"),
        Page("checkout", "🛒  Checkout && Appearance", "_build_checkout_tab", None, "manager"),
        Page("cashdrawer", "💵  Cash Drawer", "_build_cash_drawer_tab", None, "manager"),
    )),
)


def areas_for(role: str) -> list[Area]:
    """The areas (with only the pages this role may open); empty areas are dropped."""
    rank = ROLE_RANK.get(role, 0)
    out = []
    for area in AREAS:
        pages = tuple(p for p in area.pages if ROLE_RANK[p.min_role] <= rank)
        if pages:
            out.append(Area(area.key, area.title, pages))
    return out


# ── building ────────────────────────────────────────────────────────────────

class PageIndex:
    """What `window._lazy` is: look up any page by key, whichever area holds it.
    Same API as LazyTabs (page / is_built / refresh), so existing code that asks
    `self._lazy.is_built("receipt")` keeps working unchanged."""

    def __init__(self):
        self._lazies: list = []

    def add(self, lazy) -> None:
        self._lazies.append(lazy)

    def is_built(self, key: str) -> bool:
        return any(l.is_built(key) for l in self._lazies)

    def page(self, key: str):
        for l in self._lazies:
            p = l.page(key)
            if p is not None:
                return p
        return None

    def refresh(self, key: str) -> None:
        for l in self._lazies:
            l.refresh(key)


def _top_css() -> str:
    from ui.shared.theme import AMBER, DARK_CARD, LABEL_TEXT, WARM_WHITE, WHITE
    return f"""
        QTabWidget::pane{{background:{WARM_WHITE};border:none;}}
        QTabBar::tab{{background:{WHITE};color:{LABEL_TEXT};border:none;
        border-bottom:2px solid transparent;padding:10px 22px;
        font-size:13px;font-weight:600;margin-right:2px;}}
        QTabBar::tab:selected{{color:{DARK_CARD};border-bottom:2px solid {AMBER};font-weight:700;}}
        QTabBar::tab:hover{{color:{DARK_CARD};}}
    """


def _sub_css() -> str:
    from ui.shared.theme import AMBER, BORDER, DARK_CARD, LABEL_TEXT, WARM_WHITE
    return f"""
        QTabWidget::pane{{background:{WARM_WHITE};border:none;border-top:1px solid {BORDER};}}
        QTabBar::tab{{background:{WARM_WHITE};color:{LABEL_TEXT};border:none;
        border-bottom:2px solid transparent;padding:8px 16px;
        font-size:11px;font-weight:500;}}
        QTabBar::tab:selected{{color:{DARK_CARD};border-bottom:2px solid {AMBER};font-weight:700;}}
        QTabBar::tab:hover{{color:{DARK_CARD};}}
    """


def build_role_tabs(window, role: str) -> QTabWidget:
    """Create window.tabs (areas) and window._lazy (page lookup) for `role`."""
    from ui.shared.lazy_tabs import LazyTabs

    window.tabs = QTabWidget()
    window.tabs.setStyleSheet(_top_css())
    window._lazy = PageIndex()
    window._area_lazy = {}
    top = LazyTabs(window.tabs)

    def page_builder(page: Page):
        return getattr(window, page.builder)

    def page_refresher(page: Page):
        if page.refresher is None:
            return None
        return lambda: page.refresher(window)

    for area in areas_for(role):
        if len(area.pages) == 1:                       # no sub-tab row needed
            p = area.pages[0]
            top.add(p.key, area.title, page_builder(p), page_refresher(p))
            continue

        def build_area(area=area):
            inner = QTabWidget()
            inner.setStyleSheet(_sub_css())
            lazy = LazyTabs(inner)
            for p in area.pages:
                lazy.add(p.key, p.title, page_builder(p), page_refresher(p))
            lazy.start(0)
            window._lazy.add(lazy)
            window._area_lazy[area.key] = lazy
            return inner

        # Coming back to an area refreshes whichever sub-tab is showing.
        top.add(area.key, area.title, build_area,
                lambda a=area: window._area_lazy[a.key].refresh_current())

    window._lazy.add(top)                              # single-page areas live here
    top.start(0)
    return window.tabs
