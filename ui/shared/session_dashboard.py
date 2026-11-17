"""
ui/shared/session_dashboard.py
Single-session shift report used by the Reports tab (supervisor + manager).

  SessionDashboard  - summary cards plus Sales Breakdown, Tender & Financial,
                      Top Selling Items and Voids & Refunds panels
  HourlyChart       - small bar chart painted with QPainter (no chart library,
                      so memory stays low on 4 GB machines)
  SessionHistoryDialog - paged, searchable list of one cashier's past sessions
  DashboardLoader   - runs the queries off the UI thread

The Cash Drawer panel appears only for sessions that recorded a float (Setup -> Cash Drawer).

Everything here is display-only: opening, closing and printing sessions stays
in SupervisorWindow so those code paths are unchanged.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QDialog, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QFont

from utils.currency import format_currency
from ui.shared.theme import (
    AMBER, AMBER_LIGHTEST, AMBER_BG, DARK, DARK_CARD, WARM_WHITE, WHITE,
    BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT, RED, GREEN, BLUE,
)

AMBER_TEXT = "#8a5510"   # amber that stays readable as text on light backgrounds


# ── Background loading ───────────────────────────────────────────────────────

class DashboardLoader(QThread):
    """Runs session_dashboard_data off the UI thread. The caller compares
    `token` with its latest one and drops results that are out of date."""
    loaded = pyqtSignal(int, int, dict)      # token, session_id, data
    failed = pyqtSignal(int, str)

    def __init__(self, token: int, session_id: int, parent=None):
        super().__init__(parent)
        self.token, self.session_id = token, session_id

    def run(self):
        try:
            from core.db_checkout import session_dashboard_data
            self.loaded.emit(self.token, self.session_id,
                             session_dashboard_data(self.session_id))
        except Exception as e:           # never let a worker die silently
            self.failed.emit(self.token, str(e))


# ── Hourly chart ─────────────────────────────────────────────────────────────

class HourlyChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict[int, float] = {}
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_data(self, rows: list[dict]):
        self._data = {int(r["hour"]): float(r["sales"]) for r in rows}
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self._data:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No sales yet")
            return
        # Show the busy span, padded to at least 6 hours so one sale isn't a lone bar.
        lo, hi = min(self._data), max(self._data)
        while hi - lo < 5:
            if lo > 0:  lo -= 1
            if hi - lo < 5 and hi < 23: hi += 1
            if lo == 0 and hi == 23: break
        hours = list(range(lo, hi + 1))
        peak = max(self._data.values()) or 1.0
        label_h = 16
        chart_h = h - label_h - 4
        slot = w / len(hours)
        bar_w = max(4, slot * 0.6)
        small = QFont(self.font()); small.setPointSize(8); p.setFont(small)
        for i, hr in enumerate(hours):
            val = self._data.get(hr, 0.0)
            bh = 0 if val <= 0 else max(2, int(chart_h * val / peak))
            x = i * slot + (slot - bar_w) / 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(GREEN if val == peak else BLUE))
            p.drawRoundedRect(int(x), int(chart_h - bh), int(bar_w), bh, 2, 2)
            p.setPen(QColor(LABEL_TEXT))
            label = f"{hr % 12 or 12}{'a' if hr < 12 else 'p'}"
            p.drawText(int(i * slot), h - label_h, int(slot), label_h,
                       Qt.AlignmentFlag.AlignCenter, label)
        p.end()


# ── Small building blocks ────────────────────────────────────────────────────

def _panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setStyleSheet(f"QFrame{{background:{WHITE};border:1px solid {BORDER};border-radius:8px;}}")
    lay = QVBoxLayout(f); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(4)
    t = QLabel(title)
    t.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;border:none;")
    lay.addWidget(t)
    return f, lay


def _row(label: str, value: str, bold=False, color=DARK_CARD, shaded=False) -> QWidget:
    w = QWidget()
    w.setStyleSheet(f"background:{WARM_WHITE if shaded else 'transparent'};border:none;")
    h = QHBoxLayout(w); h.setContentsMargins(4, 2, 4, 2)
    weight = 700 if bold else 400
    a = QLabel(label); a.setStyleSheet(f"color:{DARK_CARD};font-size:12px;font-weight:{weight};background:transparent;")
    b = QLabel(value); b.setStyleSheet(f"color:{color};font-size:12px;font-weight:{weight};background:transparent;")
    b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    h.addWidget(a); h.addStretch(); h.addWidget(b)
    return w


def _clear(layout: QVBoxLayout, keep: int = 1):
    """Remove everything after the first `keep` items (the panel title)."""
    while layout.count() > keep:
        it = layout.takeAt(keep)
        if it.widget():
            it.widget().deleteLater()


# ── The dashboard ────────────────────────────────────────────────────────────

class SessionDashboard(QScrollArea):
    """Cards on top, panels below. Scrolls on small screens (1366x768)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"QScrollArea{{background:transparent;border:none;}}"
                           f"QScrollBar:vertical{{background:{WARM_WHITE};width:6px;border-radius:3px;}}"
                           f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;}}")
        body = QWidget(); body.setStyleSheet("background:transparent;")
        self.setWidget(body)
        root = QVBoxLayout(body); root.setContentsMargins(0, 0, 4, 0); root.setSpacing(8)

        # Summary cards
        cards = QHBoxLayout(); cards.setSpacing(8)
        self.cards: dict[str, QLabel] = {}
        for key, label, color in [
            ("total_sales", "TOTAL SALES", AMBER_TEXT), ("total_gct", "TOTAL GCT", AMBER_TEXT),
            ("transactions", "TRANSACTIONS", BLUE),    ("discounts", "DISCOUNTS", GREEN),
        ]:
            card = QFrame()
            card.setStyleSheet(f"background:{WARM_WHITE};border-radius:8px;border:1px solid {BORDER};")
            cl = QVBoxLayout(card); cl.setContentsMargins(12, 8, 12, 8); cl.setSpacing(2)
            t = QLabel(label); t.setStyleSheet(f"color:{LABEL_TEXT};font-size:10px;font-weight:700;border:none;")
            v = QLabel("—");   v.setStyleSheet(f"color:{color};font-size:22px;font-weight:700;border:none;")
            cl.addWidget(t); cl.addWidget(v)
            self.cards[key] = v; cards.addWidget(card)
        root.addLayout(cards)

        # Panels: 3 columns, collapsing to 2 on narrow windows (see resizeEvent)
        self.grid = QGridLayout(); self.grid.setSpacing(8)
        root.addLayout(self.grid)
        root.addStretch()

        self.sales_panel, self.sales_lay = _panel("Sales Breakdown")
        self.chart = HourlyChart()
        self.sales_lay.addWidget(self.chart)
        self.tender_panel, self.tender_lay = _panel("Tender & Financial Summary")
        self.top_panel,    self.top_lay    = _panel("Top Selling Items")
        self.vr_panel,     self.vr_lay     = _panel("Voids & Refunds")
        self.cash_panel,   self.cash_lay   = _panel("Cash Drawer")
        self._panels = [self.sales_panel, self.tender_panel, self.vr_panel, self.top_panel, self.cash_panel]
        self._cols = 0
        self._layout_panels(3)
        self.clear()

    # layout -----------------------------------------------------------------
    def _layout_panels(self, cols: int):
        if cols == self._cols:
            return
        self._cols = cols
        for p in self._panels:
            self.grid.removeWidget(p)
        for i, p in enumerate(self._panels):
            self.grid.addWidget(p, i // cols, i % cols, Qt.AlignmentFlag.AlignTop)
        for c in range(3):                       # reset any stretch left by the other layout
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_panels(3 if self.width() >= 900 else 2)

    # content ----------------------------------------------------------------
    def clear(self):
        for lab in self.cards.values():
            lab.setText("—")
        self.chart.set_data([])
        for lay in (self.tender_lay, self.top_lay, self.vr_lay, self.cash_lay):
            _clear(lay)
        self.cash_panel.setVisible(False)
        _clear(self.sales_lay, keep=2)    # title + chart
        for lay in (self.tender_lay, self.top_lay, self.vr_lay, self.sales_lay):
            lay.addWidget(_row("Select a cashier to see their session", "", color=MUTED))

    def show_data(self, d: dict):
        t = d["totals"]
        self.cards["total_sales"].setText(format_currency(t["total_sales"]))
        self.cards["total_gct"].setText(format_currency(t["total_gct"]))
        self.cards["transactions"].setText(str(t["transaction_count"]))
        self.cards["discounts"].setText(format_currency(t["total_discount"]))

        # Sales breakdown by group
        self.chart.set_data(d["hourly"])
        _clear(self.sales_lay, keep=2)
        groups = d["groups"]
        total = sum(g["total_sales"] or 0 for g in groups) or 1.0
        if not groups:
            self.sales_lay.addWidget(_row("No sales in this session", "", color=MUTED))
        for i, g in enumerate(groups[:8]):
            amt = g["total_sales"] or 0
            self.sales_lay.addWidget(_row(
                f"{g['group_name']}  ·  {int(g['item_count'] or 0)} items",
                f"{format_currency(amt)}  ({amt / total * 100:.0f}%)", shaded=i % 2 == 1))

        # Tender
        td = d["tender"]
        _clear(self.tender_lay)
        self.tender_lay.addWidget(_row("Total Collected", format_currency(td["collected"]), bold=True))
        self.tender_lay.addWidget(_row("Refunds", format_currency(-td["refunds"]) if td["refunds"] else format_currency(0),
                                       color=RED if td["refunds"] else DARK_CARD))
        self.tender_lay.addWidget(_row("Net Revenue", format_currency(td["net"]), bold=True, shaded=True))
        self.tender_lay.addWidget(_row("Cash", format_currency(td["cash"])))
        self.tender_lay.addWidget(_row("Card", format_currency(td["card"]), shaded=True))

        # Top sellers (quantity and amount)
        _clear(self.top_lay)
        if not d["top"]:
            self.top_lay.addWidget(_row("No sales in this session", "", color=MUTED))
        for i, it in enumerate(d["top"]):
            self.top_lay.addWidget(_row(
                f"{it['name']}", f"{int(it['qty'])} × · {format_currency(it['amount'])}", shaded=i % 2 == 1))

        # Voids & refunds
        vr = d["vr"]
        _clear(self.vr_lay)
        self.vr_lay.addWidget(_row(f"Voids ({vr['void_count']})", format_currency(vr["void_amount"]),
                                   color=RED if vr["void_count"] else DARK_CARD))
        self.vr_lay.addWidget(_row(f"Refunds ({vr['refund_count']})", format_currency(vr["refund_amount"]),
                                   color=RED if vr["refund_count"] else DARK_CARD, shaded=True))
        for r in vr["recent"]:
            kind = "Void" if r["refund_type"] == "void" else r["refund_type"].capitalize()
            line = _row(f"{r['receipt_number']}  ·  {kind}", format_currency(r["value"]))
            if r.get("reason"):
                line.setToolTip(r["reason"])
            self.vr_lay.addWidget(line)
        if not vr["recent"]:
            self.vr_lay.addWidget(_row("None this session", "", color=MUTED))

        self._show_cash(d.get("cash"))

    def _show_cash(self, c):
        """Float, cash sales and refunds, expected, counted, variance. Hidden when the
        session recorded no float (tracking was off when it opened)."""
        _clear(self.cash_lay)
        self.cash_panel.setVisible(c is not None)
        if c is None:
            return
        def m(v):                                    # -$2.50, not $-2.50
            return f"-{format_currency(abs(v))}" if v < 0 else format_currency(v)
        L = self.cash_lay
        L.addWidget(_row("Opening float", m(c["float"])))
        L.addWidget(_row("Cash sales", m(c["cash_sales"]), shaded=True))
        L.addWidget(_row("Cash refunds", m(-c["cash_refunds"]) if c["cash_refunds"] else m(0),
                         color=RED if c["cash_refunds"] else DARK_CARD))
        L.addWidget(_row("Expected cash" + (" so far" if c["is_open"] else ""), m(c["expected"]),
                         bold=True, shaded=True))
        if c["counted"] is not None:
            L.addWidget(_row("Counted cash", m(c["counted"]), bold=True))
            v = c["variance"]
            if v == 0:
                L.addWidget(_row("Variance", "Balanced", bold=True, color=GREEN, shaded=True))
            else:
                L.addWidget(_row("Variance", f"{'+' if v > 0 else '-'}{format_currency(abs(v))}  "
                                 f"({'over' if v > 0 else 'short'})", bold=True,
                                 color=AMBER_TEXT if v > 0 else RED, shaded=True))
            who = f"Counted by {c['counted_by']}" if c["counted_by"] else "Counted"
            L.addWidget(_row(f"{who} · {str(c['counted_at'])[:16]}", "", color=MUTED))
        elif c["pending"]:
            L.addWidget(_row("Counted cash", "Count pending", bold=True, color=AMBER_TEXT))
        else:
            L.addWidget(_row("Counted cash", "after the session closes", color=MUTED))

    def show_error(self, msg: str):
        self.clear()
        _clear(self.tender_lay)
        self.tender_lay.addWidget(_row("Could not load this session", "", color=RED))
        self.tender_lay.setToolTip(msg)


# ── History popup ────────────────────────────────────────────────────────────

class SessionHistoryDialog(QDialog):
    """Paged list of one cashier's sessions. Double-click picks one."""
    PAGE = 30

    def __init__(self, user_id: int, cashier_name: str, input_style: str,
                 table_style: str, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.selected_id: int | None = None
        self._offset = 0
        self.setWindowTitle(f"Session history — {cashier_name}")
        self.setMinimumSize(640, 460)
        self.setStyleSheet(f"background:{WHITE};")
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(8)

        row = QHBoxLayout(); row.setSpacing(8)
        self.f_num  = QLineEdit(); self.f_num.setPlaceholderText("Session #")
        self.f_from = QLineEdit(); self.f_from.setPlaceholderText("From  YYYY-MM-DD")
        self.f_to   = QLineEdit(); self.f_to.setPlaceholderText("To  YYYY-MM-DD")
        for f in (self.f_num, self.f_from, self.f_to):
            f.setFixedHeight(30); f.setStyleSheet(input_style)
            f.returnPressed.connect(self._reload)
            row.addWidget(f)
        go = QPushButton("Search"); go.setFixedHeight(30); go.clicked.connect(self._reload)
        go.setStyleSheet(f"QPushButton{{background:{AMBER};color:{DARK};border:none;border-radius:15px;"
                         f"font-size:12px;font-weight:700;padding:0 16px;}}")
        row.addWidget(go)
        lay.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Session", "Status", "Opened", "Closed"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False)
        self.table.setStyleSheet(table_style)
        self.table.itemDoubleClicked.connect(self._pick)
        lay.addWidget(self.table, stretch=1)

        foot = QHBoxLayout()
        self.more = QPushButton("Load more")
        self.more.setFixedHeight(30); self.more.clicked.connect(self._load_page)
        self.hint = QLabel("Double-click a session to view it")
        self.hint.setStyleSheet(f"color:{MUTED};font-size:11px;")
        foot.addWidget(self.hint); foot.addStretch(); foot.addWidget(self.more)
        lay.addLayout(foot)
        self._reload()

    def _reload(self):
        self.table.setRowCount(0); self._offset = 0
        self._load_page(first=True)

    def _load_page(self, first=False):
        from core.db_users import get_sessions_page
        # Default view: the last 30 sessions, newest first (paged).
        rows = get_sessions_page(self.user_id, self.PAGE, self._offset,
                                 self.f_from.text().strip(), self.f_to.text().strip(),
                                 self.f_num.text().strip())
        self._offset += len(rows)
        for s in rows:
            i = self.table.rowCount(); self.table.insertRow(i); self.table.setRowHeight(i, 34)
            num = QTableWidgetItem(f"#{s['id']:05d}"); num.setData(Qt.ItemDataRole.UserRole, s["id"])
            stat = QTableWidgetItem("Active" if s["status"] == "open" else "Closed")
            stat.setForeground(QColor(GREEN if s["status"] == "open" else MUTED))
            for c, it in enumerate([
                num, stat,
                QTableWidgetItem(str(s["opened_at"])[:16]),
                QTableWidgetItem(str(s["closed_at"])[:16] if s["closed_at"] else "—"),
            ]):
                self.table.setItem(i, c, it)
        self.more.setEnabled(len(rows) == self.PAGE)
        if first and not rows:
            self.hint.setText("No sessions match")

    def _pick(self, item):
        first = self.table.item(item.row(), 0)
        if first:
            self.selected_id = first.data(Qt.ItemDataRole.UserRole)
            self.accept()
