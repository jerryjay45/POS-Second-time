"""
Lazy tab pages for a QTabWidget.

Building every tab when a window opens is slow on a big catalog (the Manager
window took ~2 s, the Supervisor ~1.5 s, at 43k products) and most tabs are
never opened in a session. LazyTabs:

  * builds a tab's page the FIRST time it is shown (the first tab is built
    straight away), and then keeps it alive — nothing is ever unloaded, so
    search text, the page you were on and half-filled fields survive switching
    tabs;
  * calls the tab's optional *refresher* every time you come back to it, so
    lists show current data (new sales, stock changes, other terminals).
    Refreshers should only reload table data — never reset the user's input.

Usage (inside a window that owns `self.tabs = QTabWidget()`):

    self._lazy = LazyTabs(self.tabs)
    self._lazy.add("products", "Products", self._build_products_tab,
                   refresher=lambda: self._load_products(self._pg_search))
    self._lazy.add("quickkeys", "Quick Keys", self._build_quickkeys_tab)
    self._lazy.start()

Other code that needs a tab's widgets before the user has opened it must check
`self._lazy.is_built("products")` first — the widgets don't exist until then.
"""
from __future__ import annotations

import traceback
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget


class LazyTabs:
    def __init__(self, tabs: QTabWidget):
        self._tabs    = tabs
        self._entries: list[dict] = []
        self._busy    = False          # re-entrancy guard while a page is being built

    # ── setup ────────────────────────────────────────────────────────────
    def add(self, key: str, title: str, builder: Callable[[], QWidget],
            refresher: Callable[[], None] | None = None) -> None:
        placeholder = QWidget()
        self._entries.append({"key": key, "title": title, "builder": builder,
                              "refresher": refresher, "page": None,
                              "placeholder": placeholder})
        self._tabs.addTab(placeholder, title)

    def start(self, index: int = 0) -> None:
        """Call once, after every add(). Builds the starting tab immediately."""
        self._tabs.blockSignals(True)
        self._tabs.setCurrentIndex(index)
        self._tabs.blockSignals(False)
        self._tabs.currentChanged.connect(self._on_changed)
        self._activate(index)

    # ── queries ──────────────────────────────────────────────────────────
    def is_built(self, key: str) -> bool:
        e = self._entry(key)
        return bool(e and e["page"] is not None)

    def page(self, key: str):
        """The tab's page widget, or None if it hasn't been opened yet."""
        e = self._entry(key)
        return e["page"] if e else None

    def refresh(self, key: str) -> None:
        """Run a built tab's refresher now (no-op if it isn't built)."""
        e = self._entry(key)
        if e and e["page"] is not None:
            self._run_refresher(e)

    # ── internals ────────────────────────────────────────────────────────
    def _entry(self, key: str):
        return next((e for e in self._entries if e["key"] == key), None)

    def _on_changed(self, index: int) -> None:
        if index >= 0 and not self._busy:
            self._activate(index)

    def _activate(self, index: int) -> None:
        if not (0 <= index < len(self._entries)):
            return
        e = self._entries[index]
        if e["page"] is None:
            self._build(index, e)
        else:
            self._run_refresher(e)

    def _run_refresher(self, e: dict) -> None:
        if e["refresher"] is None:
            return
        try:
            e["refresher"]()
        except Exception:
            # A failed refresh must never take the window down — the tab simply
            # keeps showing what it had.
            traceback.print_exc()

    def _build(self, index: int, e: dict) -> None:
        self._busy = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                page = e["builder"]()
            except Exception as exc:
                traceback.print_exc()
                self._show_error(e, exc)      # stays unbuilt -> retried on next visit
                return
        finally:
            QApplication.restoreOverrideCursor()
            self._busy = False

        tabs = self._tabs
        was_current = tabs.currentIndex() == index
        tabs.blockSignals(True)
        try:
            tabs.removeTab(index)
            tabs.insertTab(index, page, e["title"])
            if was_current:
                tabs.setCurrentIndex(index)
        finally:
            tabs.blockSignals(False)
        e["placeholder"].deleteLater()
        e["placeholder"] = None
        e["page"] = page

    def _show_error(self, e: dict, exc: Exception) -> None:
        ph = e["placeholder"]
        if ph is None:
            return
        if ph.layout() is None:
            lay = QVBoxLayout(ph)
            self_lbl = QLabel()
            self_lbl.setObjectName("lazyTabError")
            self_lbl.setWordWrap(True)
            self_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(self_lbl)
        lbl = ph.findChild(QLabel, "lazyTabError")
        if lbl is not None:
            lbl.setText(f"Could not load this tab:\n{exc}\n\nSwitch to another tab and back to try again.")
