"""
ui/supervisor/stock_tab.py
Stock management tab.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QComboBox, QLabel, QFrame, QHeaderView,
    QSpinBox, QAbstractItemView, QSplitter, QDialog,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QIcon, QPixmap

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_BG, AMBER_LIGHTEST,
    DARK, DARK_CARD, WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT, RED, RED_LIGHT, GREEN, GREEN_LIGHT, BLUE,
)
from core.db_products import (
    get_products, count_products, adjust_stock,
    get_all_stock_adjustments, get_low_stock_products,
    get_stock_adjustments, get_product_by_id,
    get_variant_groups, adjust_variant_group_stock, get_low_stock_variant_groups,
)
from core.db_config import get_int
from core.db_users import get_user_by_id


def _stock_color(stock: int, threshold: int) -> str:
    if stock == 0:         return RED
    if stock <= threshold: return AMBER_TEXT_ON_LIGHT
    return GREEN


# AMBER (#EF9F27) and AMBER_DARK (#BA7517), used directly as TEXT color
# rather than a background, measured well under the 4.5:1 WCAG floor
# against both white and AMBER_BG — same failure pattern found and fixed
# throughout the cashier section. Scoped locally rather than changing the
# shared constants, which are used correctly elsewhere in this file as
# backgrounds/borders.
AMBER_TEXT_ON_LIGHT = "#8a5510"


# ── Hand-painted icons ───────────────────────────────────────────────────────
# Drawn glyphs instead of Unicode dingbats/emoji: emoji fonts render wildly
# differently across Windows/macOS/Linux (different weight, color, baseline),
# which is exactly the kind of OS-dependent look this pass is removing.

def _draw_icon(kind: str, color: str, size: int = 19) -> QIcon:
    scale = 4
    s = size * scale
    pm = QPixmap(s, s); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color)); pen.setWidthF(s * 0.12)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    m = s * 0.22
    if kind == "clear":
        p.drawLine(int(m), int(m), int(s - m), int(s - m))
        p.drawLine(int(s - m), int(m), int(m), int(s - m))
    elif kind == "history":
        # Clock face: circle + hour/minute hands, universally read as "history".
        r = s * 0.34
        cx = cy = s / 2
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        p.drawLine(int(cx), int(cy), int(cx), int(cy - r * 0.55))
        p.drawLine(int(cx), int(cy), int(cx + r * 0.45), int(cy + r * 0.1))
    elif kind == "plus":
        p.drawLine(int(s / 2), int(m), int(s / 2), int(s - m))
        p.drawLine(int(m), int(s / 2), int(s - m), int(s / 2))
    elif kind == "minus":
        p.drawLine(int(m), int(s / 2), int(s - m), int(s / 2))
    p.end()
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
    return QIcon(pm)


def _icon_btn(kind: str, tooltip: str = "") -> QPushButton:
    """Small square icon-only button (search-bar clear buttons etc.)."""
    b = QPushButton(); b.setFixedSize(34, 34)
    b.setToolTip(tooltip); b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setIcon(_draw_icon(kind, DARK_CARD)); b.setIconSize(QSize(16, 16))
    b.setStyleSheet(
        f"QPushButton{{background:{WARM_WHITE};border:1.5px solid {BORDER};"
        f"border-radius:7px;outline:none;}}"
        f"QPushButton:hover{{border-color:{AMBER};background:{AMBER_LIGHTEST};}}"
        f"QPushButton:pressed{{background:{BORDER_LIGHT};}}"
    )
    return b


def _compact_icon_btn(kind: str, color: str, tint: str, tooltip: str = "") -> QPushButton:
    """Small (28px) colored icon-only button — used where a text button
    ("+ Add" / "− Remove") wouldn't fit a narrow table cell alongside a
    spinbox. The icon color itself stays fixed (Qt can't restyle a
    QIcon's pixmap per widget-state via stylesheet alone); only the
    background/border shift on hover, matching _icon_btn's approach."""
    b = QPushButton(); b.setFixedSize(28, 28)
    b.setToolTip(tooltip); b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setIcon(_draw_icon(kind, color)); b.setIconSize(QSize(14, 14))
    b.setStyleSheet(
        f"QPushButton{{background:{WARM_WHITE};border:1.5px solid {color};"
        f"border-radius:6px;outline:none;}}"
        f"QPushButton:hover{{background:{tint};}}"
        f"QPushButton:pressed{{background:{color};}}"
    )
    return b


def _text_btn(text: str, color: str, height: int = 36, filled_hover: bool = True) -> QPushButton:
    """Outlined text button with color, and every visual state (hover/pressed/
    disabled/focus) spelled out explicitly, so nothing is left for the OS's
    native button chrome to render."""
    b = QPushButton(text); b.setFixedHeight(height)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    hover_bg = color if filled_hover else AMBER_LIGHTEST
    hover_fg = "white" if filled_hover else color
    b.setStyleSheet(
        f"QPushButton{{background:transparent;color:{color};"
        f"border:1.5px solid {color};border-radius:7px;"
        f"font-size:12px;font-weight:700;padding:0 10px;outline:none;}}"
        f"QPushButton:hover{{background:{hover_bg};color:{hover_fg};}}"
        f"QPushButton:pressed{{background:{color};color:white;}}"
        f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};background:transparent;}}"
    )
    return b


def _lineedit_style() -> str:
    return (
        f"QLineEdit{{background:{WHITE};border:2px solid {BORDER};"
        f"border-radius:7px;padding:0 10px;font-size:13px;color:{DARK_CARD};outline:none;}}"
        f"QLineEdit:hover{{border-color:{AMBER_LIGHTEST};}}"
        f"QLineEdit:focus{{border-color:{AMBER};}}"
    )


def _combobox_style(font_size: int = 13) -> str:
    return (
        f"QComboBox{{background:{WHITE};border:2px solid {BORDER};"
        f"border-radius:7px;padding:0 10px;font-size:{font_size}px;color:{DARK_CARD};outline:none;}}"
        f"QComboBox:hover{{border-color:{AMBER_LIGHTEST};}}"
        f"QComboBox:focus{{border-color:{AMBER};}}"
        f"QComboBox::drop-down{{border:none;width:22px;}}"
        f"QComboBox QAbstractItemView{{background:{WHITE};color:{DARK_CARD};"
        f"selection-background-color:{AMBER_LIGHTEST};selection-color:{DARK_CARD};"
        f"border:1px solid {BORDER};outline:none;}}"
    )


def _neutral_btn(text: str, height: int = 36) -> QPushButton:
    """Neutral (gray) outlined button — used for Cancel/Close-style actions."""
    b = QPushButton(text); b.setFixedHeight(height)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{background:transparent;color:{LABEL_TEXT};"
        f"border:1.5px solid {BORDER};border-radius:7px;"
        f"font-size:12px;font-weight:600;padding:0 12px;outline:none;}}"
        f"QPushButton:hover{{border-color:{AMBER};color:{AMBER_TEXT_ON_LIGHT};background:{AMBER_LIGHTEST};}}"
        f"QPushButton:pressed{{background:{BORDER_LIGHT};}}"
        f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};background:transparent;}}"
    )
    return b


# ── History Dialog ────────────────────────────────────────────────────────────

class HistoryDialog(QDialog):
    def __init__(self, product_id: int, product_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Adjustment History — {product_name}")
        self.setMinimumSize(700, 480)
        self.setStyleSheet(f"QDialog{{background:{WARM_WHITE};}}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18); lay.setSpacing(12)

        # Header
        title = QLabel(f"History for {product_name}")
        title.setStyleSheet(f"color:{DARK_CARD};font-size:15px;font-weight:700;")
        lay.addWidget(title)

        # Table
        table = QTableWidget(); table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Change", "Reason", "By", "When", "Notes"])
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setStyleSheet(self._table_style())

        rows = get_stock_adjustments(product_id, limit=200)
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        for i, adj in enumerate(rows):
            table.insertRow(i); table.setRowHeight(i, 36)
            qty   = adj["qty_change"]
            sign  = "＋" if qty > 0 else "−"
            color = GREEN if qty > 0 else RED
            qi = QTableWidgetItem(f"{sign}{abs(qty)}")
            qi.setForeground(QColor(color)); qi.setTextAlignment(C)
            f = QFont(); f.setBold(True); qi.setFont(f)
            table.setItem(i, 0, qi)
            table.setItem(i, 1, QTableWidgetItem(adj.get("reason", "—")))
            user = get_user_by_id(adj["adjusted_by"]) if adj.get("adjusted_by") else None
            table.setItem(i, 2, QTableWidgetItem(user["full_name"] if user else "System"))
            table.setItem(i, 3, QTableWidgetItem(str(adj.get("adjusted_at", ""))[:16]))
            table.setItem(i, 4, QTableWidgetItem(""))

        if not rows:
            table.insertRow(0); table.setRowHeight(0, 48)
            lbl = QTableWidgetItem("No adjustments recorded yet.")
            lbl.setForeground(QColor(MUTED)); lbl.setTextAlignment(C)
            table.setItem(0, 0, lbl)
            table.setSpan(0, 0, 1, 5)

        lay.addWidget(table, stretch=1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        close_btn = _neutral_btn("Close", height=34)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.reject)
        bottom_row.addWidget(close_btn)
        lay.addLayout(bottom_row)

    def _table_style(self) -> str:
        return (
            f"QTableWidget{{background:{WHITE};border:1px solid {BORDER};"
            f"border-radius:8px;font-size:13px;font-weight:500;}}"
            f"QTableWidget::item{{padding:8px 12px;"
            f"border-bottom:1px solid {BORDER_LIGHT};color:{DARK_CARD};}}"
            f"QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}"
            f"QHeaderView::section{{background:{DARK_CARD};color:{AMBER};"
            f"font-size:12px;font-weight:700;padding:8px 12px;border:none;"
            f"border-right:1px solid #333;}}"
        )


# ── Stock Adjustment Dialog ──────────────────────────────────────────────────

class StockAdjustDialog(QDialog):
    """Pop-up form for adding/removing stock on a single product — mirrors the
    pop-up pattern used by ProductDialog on the Products tab."""

    def __init__(self, user: dict, product_id: int, product_name: str,
                 threshold: int, parent=None):
        super().__init__(parent)
        self.user       = user
        self.product_id = product_id
        self.threshold  = threshold
        self.changed    = False  # set True if any adjustment was made

        self.setWindowTitle(f"Adjust Stock — {product_name}")
        self.setMinimumWidth(400)
        self.setStyleSheet(f"QDialog{{background:{WARM_WHITE};}}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20); lay.setSpacing(14)

        self.title_lbl = QLabel(product_name)
        self.title_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:16px;font-weight:700;")
        self.title_lbl.setWordWrap(True)
        lay.addWidget(self.title_lbl)

        # ── Current-stock stat card ──────────────────────────────────
        # An explicit bordered/background card rather than a bare label, so
        # the number reads clearly regardless of OS font rendering.
        self.stock_card = QFrame()
        self.stock_card.setStyleSheet(
            f"QFrame{{background:{WARM_WHITE};border:1.5px solid {BORDER};border-radius:9px;}}"
        )
        sc = QVBoxLayout(self.stock_card)
        sc.setContentsMargins(14, 10, 14, 10); sc.setSpacing(2)
        sc.addWidget(self._section_lbl("Current Stock"))
        self.stock_value_lbl = QLabel("—")
        self.stock_value_lbl.setStyleSheet("font-size:22px;font-weight:800;")
        sc.addWidget(self.stock_value_lbl)
        self.stock_note_lbl = QLabel("")
        self.stock_note_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:500;")
        self.stock_note_lbl.setWordWrap(True)
        self.stock_note_lbl.setVisible(False)
        sc.addWidget(self.stock_note_lbl)
        lay.addWidget(self.stock_card)

        lay.addWidget(self._section_lbl("Quantity"))
        self.qty = QSpinBox()
        self.qty.setMinimum(1); self.qty.setMaximum(99999); self.qty.setValue(1)
        self.qty.setFixedHeight(38)
        self.qty.setStyleSheet(
            f"QSpinBox{{background:{WHITE};border:2px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:13px;color:{DARK_CARD};outline:none;}}"
            f"QSpinBox:focus{{border-color:{AMBER};}}"
            f"QSpinBox:hover{{border-color:{AMBER_LIGHTEST};}}"
        )
        lay.addWidget(self.qty)

        lay.addWidget(self._section_lbl("Reason"))
        self.reason = QComboBox()
        self.reason.addItems(["Restock", "Damaged", "Correction", "Return", "Other"])
        self.reason.setFixedHeight(38)
        self.reason.setStyleSheet(_combobox_style(13))
        lay.addWidget(self.reason)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        add_btn = _text_btn("＋  Add Stock", GREEN)
        add_btn.clicked.connect(self._do_add)
        rem_btn = _text_btn("−  Remove Stock", RED)
        rem_btn.clicked.connect(self._do_remove)
        btn_row.addWidget(add_btn, stretch=1); btn_row.addWidget(rem_btn, stretch=1)
        lay.addLayout(btn_row)

        self.feedback = QLabel("")
        self.feedback.setStyleSheet(f"color:{GREEN};font-size:12px;font-weight:600;")
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feedback.setFixedHeight(18)
        lay.addWidget(self.feedback)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{BORDER_LIGHT};max-height:1px;border:none;")
        lay.addWidget(sep)

        bottom_row = QHBoxLayout(); bottom_row.setSpacing(8)
        hist_btn = _neutral_btn("View History", height=36)
        hist_btn.setIcon(_draw_icon("history", LABEL_TEXT)); hist_btn.setIconSize(QSize(15, 15))
        hist_btn.clicked.connect(self._show_history)
        close_btn = _neutral_btn("Close", height=36)
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(hist_btn, stretch=1); bottom_row.addWidget(close_btn)
        lay.addLayout(bottom_row)

        self._refresh_stock_label()

    def _refresh_stock_label(self):
        p = get_product_by_id(self.product_id)
        stock = p["effective_stock"] if p else 0
        color = _stock_color(stock, self.threshold)
        self.stock_value_lbl.setStyleSheet(f"color:{color};font-size:22px;font-weight:800;")
        self.stock_value_lbl.setText(f"{stock} unit{'s' if stock != 1 else ''}")
        if p and p.get("variant_group_id"):
            self.stock_note_lbl.setText(
                f"Shared with {p.get('variant_group_name', 'variant group')}"
            )
            self.stock_note_lbl.setVisible(True)
        else:
            self.stock_note_lbl.setVisible(False)

    def _do_add(self):
        qty, reason = self.qty.value(), self.reason.currentText()
        adjust_stock(self.product_id, qty, reason, self.user["id"])
        self.changed = True
        self._refresh_stock_label()
        self.feedback.setStyleSheet(f"color:{GREEN};font-size:12px;font-weight:600;")
        self.feedback.setText(f"✓  Added {qty} unit{'s' if qty != 1 else ''}")

    def _do_remove(self):
        qty, reason = self.qty.value(), self.reason.currentText()
        adjust_stock(self.product_id, -qty, reason, self.user["id"])
        self.changed = True
        self._refresh_stock_label()
        self.feedback.setStyleSheet(f"color:{AMBER_TEXT_ON_LIGHT};font-size:12px;font-weight:600;")
        self.feedback.setText(f"✓  Removed {qty} unit{'s' if qty != 1 else ''}")

    def _show_history(self):
        p = get_product_by_id(self.product_id)
        name = p["name"] if p else self.title_lbl.text()
        dlg = HistoryDialog(self.product_id, name, self)
        dlg.exec()

    def _section_lbl(self, text: str) -> QLabel:
        l = QLabel(text.upper())
        l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
        return l


# ── Stock Tab ─────────────────────────────────────────────────────────────────

class StockTab(QWidget):

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user                   = user
        self._threshold             = get_int("low_stock_threshold", 5)
        self._pg_page               = 0
        self._pg_per_page           = 50
        self._pg_search             = ""
        self._pool_search           = ""
        self._build_ui()
        self._refresh_all()

    def _clear_search_btn(self, tooltip: str = "Clear search") -> QPushButton:
        return _icon_btn("clear", tooltip)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8); root.setSpacing(8)

        # ── Alert bar ─────────────────────────────────────────────────
        self.alert_frame = QFrame()
        self.alert_frame.setStyleSheet(
            f"QFrame{{background:{AMBER_BG};border:1.5px solid {AMBER};border-radius:8px;}}"
        )
        af = QHBoxLayout(self.alert_frame)
        af.setContentsMargins(12, 6, 12, 6); af.setSpacing(8)
        alert_icon = QLabel("⚠")
        alert_icon.setStyleSheet(f"color:{AMBER_TEXT_ON_LIGHT};font-size:14px;font-weight:700;background:transparent;")
        self.alert_lbl = QLabel("")
        self.alert_lbl.setStyleSheet(f"color:{AMBER_TEXT_ON_LIGHT};font-size:12px;font-weight:600;background:transparent;")
        self.alert_lbl.setWordWrap(True)
        dismiss_btn = QPushButton("Dismiss"); dismiss_btn.setFixedHeight(26)
        dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER_TEXT_ON_LIGHT};"
            f"border:1px solid {AMBER};border-radius:5px;font-size:11px;"
            f"font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:{AMBER};color:{DARK};}}"
        )
        dismiss_btn.clicked.connect(lambda: self.alert_frame.setVisible(False))
        af.addWidget(alert_icon); af.addWidget(self.alert_lbl, stretch=1); af.addWidget(dismiss_btn)
        self.alert_frame.setVisible(False)
        root.addWidget(self.alert_frame)

        # ── Splitter ──────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};width:1px;}}")

        # ── Left: stock list ──────────────────────────────────────────
        left = QFrame()
        left.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        ll = QVBoxLayout(left); ll.setContentsMargins(10, 10, 10, 10); ll.setSpacing(8)

        # Toolbar
        tb = QHBoxLayout(); tb.setSpacing(6)
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("🔍  Search by product name or group…")
        self.search_inp.setFixedHeight(34)
        self.search_inp.setStyleSheet(_lineedit_style())
        self.search_inp.returnPressed.connect(self._search)

        clr_btn = self._clear_search_btn("Clear search")
        clr_btn.clicked.connect(lambda: (
            self.search_inp.clear(),
            self.search_inp.setFocus(),
            self._search(),
        ))

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All Stock", "Low Stock", "Out of Stock"])
        self.filter_combo.setFixedHeight(34); self.filter_combo.setFixedWidth(130)
        self.filter_combo.setStyleSheet(_combobox_style(12))
        self.filter_combo.currentIndexChanged.connect(self._search)
        refresh_btn = self._outline_btn("↻  Refresh"); refresh_btn.clicked.connect(self._refresh_all)
        tb.addWidget(self.search_inp, stretch=1)
        tb.addWidget(clr_btn)
        tb.addSpacing(4)
        tb.addWidget(self.filter_combo); tb.addWidget(refresh_btn)
        ll.addLayout(tb)

        # Stock table — 4 cols: Product, Group, Stock, Actions
        self.stock_table = QTableWidget(); self.stock_table.setColumnCount(4)
        self.stock_table.setHorizontalHeaderLabels(["Product", "Group", "Stock", "Actions"])
        hh = self.stock_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.stock_table.setColumnWidth(2, 70)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        # Was 150px — "Adjust" + "History" side by side measured a ~140px
        # bare minimum (font metrics: "Adjust" ~61px, "History" ~67px,
        # plus spacing/margins), leaving almost no slack and causing
        # visible truncation. 170px gives real breathing room without
        # excess dead space (190 left a visibly large empty gap).
        self.stock_table.setColumnWidth(3, 170)
        self.stock_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stock_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stock_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.stock_table.verticalHeader().setVisible(False)
        self.stock_table.setShowGrid(False)
        self.stock_table.setStyleSheet(self._table_style())
        self.stock_table.doubleClicked.connect(self._on_stock_dbl_click)
        ll.addWidget(self.stock_table, stretch=1)

        # Pagination
        pg_row = QHBoxLayout(); pg_row.setSpacing(8)
        self._pg_prev = self._outline_btn("← Prev"); self._pg_prev.setFixedWidth(80)
        self._pg_prev.clicked.connect(self._prev_page)
        self._pg_label = QLabel("Page 1 of 1")
        self._pg_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        self._pg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pg_next = self._outline_btn("Next →"); self._pg_next.setFixedWidth(80)
        self._pg_next.clicked.connect(self._next_page)
        pg_row.addStretch()
        pg_row.addWidget(self._pg_prev); pg_row.addWidget(self._pg_label); pg_row.addWidget(self._pg_next)
        pg_row.addStretch()
        ll.addLayout(pg_row)

        # ── Right: variant group stock list ─────────────────────────────
        # (Replaces the old inline adjustment panel — single-product stock
        # adjustments now happen in a pop-up StockAdjustDialog instead, the
        # same pop-up pattern the Products tab uses for add/edit.)
        right = QFrame()
        right.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        rl = QVBoxLayout(right); rl.setContentsMargins(10, 10, 10, 10); rl.setSpacing(8)

        pool_hdr = QHBoxLayout()
        pool_title = QLabel("🔗  Variant Group Stock")
        pool_title.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;background:transparent;")
        pool_hdr.addWidget(pool_title)
        pool_hdr.addStretch()
        self.pool_refresh_btn = QPushButton("↻  Refresh")
        self.pool_refresh_btn.setFixedHeight(26)
        self.pool_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pool_refresh_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{AMBER_TEXT_ON_LIGHT};border:1px solid {AMBER};"
            f"border-radius:5px;font-size:11px;font-weight:600;padding:0 10px;}}"
            f"QPushButton:hover{{background:{AMBER};color:{DARK};}}"
        )
        self.pool_refresh_btn.clicked.connect(self._load_pool_table)
        pool_hdr.addWidget(self.pool_refresh_btn)
        rl.addLayout(pool_hdr)

        # Search bar — same pattern as the Products tab's search bar
        pool_tb = QHBoxLayout(); pool_tb.setSpacing(6)
        self.pool_search_inp = QLineEdit()
        self.pool_search_inp.setPlaceholderText("🔍  Search variant groups…")
        self.pool_search_inp.setFixedHeight(34)
        self.pool_search_inp.setStyleSheet(_lineedit_style())
        self.pool_search_inp.returnPressed.connect(self._pool_search_fn)
        self.pool_search_inp.textChanged.connect(self._pool_search_fn)

        pool_clr_btn = self._clear_search_btn("Clear search")
        pool_clr_btn.clicked.connect(lambda: (
            self.pool_search_inp.clear(),
            self.pool_search_inp.setFocus(),
        ))

        pool_tb.addWidget(self.pool_search_inp, stretch=1)
        pool_tb.addWidget(pool_clr_btn)
        rl.addLayout(pool_tb)

        # 4 columns now — "Case Qty" dropped: units-per-case lives on each
        # case PRODUCT (case_qty), not on the variant group itself, since a
        # group can be the source for multiple differently-sized cases.
        self.pool_table = QTableWidget(); self.pool_table.setColumnCount(4)
        self.pool_table.setHorizontalHeaderLabels(
            ["Group Name", "Stock", "Add Stock", "Remove Stock"]
        )
        ph = self.pool_table.horizontalHeader()
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        ph.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        # Column widths sized to whichever is larger: the compact
        # spinbox+icon-button content (~92px) or the header label itself
        # ("Remove Stock" alone measures ~86px of text) — my first pass
        # sized purely for content and clipped the "Remove Stock" header.
        self.pool_table.setColumnWidth(2, 110)
        self.pool_table.setColumnWidth(3, 130)
        self.pool_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pool_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.pool_table.verticalHeader().setVisible(False)
        self.pool_table.setShowGrid(False)
        self.pool_table.setStyleSheet(self._table_style())
        rl.addWidget(self.pool_table, stretch=1)

        self.pool_empty_lbl = QLabel("No variant groups have been set up yet.")
        self.pool_empty_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;")
        self.pool_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pool_empty_lbl.setVisible(False)
        rl.addWidget(self.pool_empty_lbl)

        splitter.addWidget(left); splitter.addWidget(right)
        splitter.setStretchFactor(0, 1); splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _refresh_all(self):
        self._threshold = get_int("low_stock_threshold", 5)
        self._load_stock_table()
        self._load_pool_table()
        self._refresh_alert()

    def _refresh_alert(self):
        low = get_low_stock_products(self._threshold)
        low_pool = get_low_stock_variant_groups(self._threshold)
        if not low and not low_pool:
            self.alert_frame.setVisible(False); return
        out  = [p for p in low if p["stock"] == 0]
        warn = [p for p in low if 0 < p["stock"] <= self._threshold]
        parts = []
        if out:       parts.append(f"{len(out)} out of stock")
        if warn:      parts.append(f"{len(warn)} low (≤{self._threshold})")
        if low_pool:  parts.append(f"{len(low_pool)} variant group{'s' if len(low_pool) != 1 else ''} low")
        names = ", ".join(p["name"] for p in low[:4])
        if low_pool:
            names += (", " if names else "") + ", ".join(g["name"] for g in low_pool[:2])
        if len(low) + len(low_pool) > 5: names += f"  +{len(low)+len(low_pool)-5} more"
        self.alert_lbl.setText(f"{' · '.join(parts)}:  {names}")
        self.alert_frame.setVisible(True)

    def _load_pool_table(self):
        """Populate the Variant Group Stock panel, filtered by search text."""
        groups = get_variant_groups()
        if self._pool_search:
            groups = [g for g in groups if self._pool_search.lower() in g["name"].lower()]

        self.pool_table.setVisible(bool(groups))
        self.pool_empty_lbl.setVisible(not groups)
        if not get_variant_groups():
            self.pool_empty_lbl.setText("No variant groups have been set up yet.")
        elif not groups:
            self.pool_empty_lbl.setText("No variant groups match your search.")
        if not groups:
            self.pool_table.setRowCount(0)
            return
        self.pool_table.setRowCount(0)
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter

        for row, g in enumerate(groups):
            self.pool_table.insertRow(row)
            self.pool_table.setRowHeight(row, 40)

            name_item = QTableWidgetItem(g["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, g["id"])
            self.pool_table.setItem(row, 0, name_item)

            stock = g.get("stock", 0)
            color = RED if stock == 0 else (AMBER_TEXT_ON_LIGHT if stock <= self._threshold else GREEN)
            label = "Out" if stock == 0 else (f"{stock} ⚠" if stock <= self._threshold else str(stock))
            si = QTableWidgetItem(label)
            si.setForeground(QColor(color)); si.setTextAlignment(C)
            f = QFont(); f.setBold(True); si.setFont(f)
            self.pool_table.setItem(row, 1, si)

            # Add Stock widget — spinbox + compact colored icon button.
            # The old "+ Add"/"− Remove" text buttons needed ~87px min for
            # "Remove" alone (measured), which didn't fit the 140px column
            # alongside a spinbox — that's what was actually causing the
            # truncation. Icon-only buttons are unambiguous here (a
            # universal +/− paired with the row's own group name) and take
            # a fraction of the width, freeing real room for Group Name.
            add_w = QWidget(); add_l = QHBoxLayout(add_w)
            add_l.setContentsMargins(4, 2, 4, 2); add_l.setSpacing(4)
            add_spin = QSpinBox(); add_spin.setMinimum(1); add_spin.setMaximum(9999)
            add_spin.setValue(1); add_spin.setFixedHeight(28); add_spin.setFixedWidth(52)
            add_spin.setStyleSheet(
                f"QSpinBox{{background:{WHITE};border:1px solid {BORDER};"
                f"border-radius:5px;padding:0 4px;font-size:11px;color:{DARK_CARD};outline:none;}}"
                f"QSpinBox:focus{{border-color:{AMBER};}}"
            )
            add_btn = _compact_icon_btn("plus", GREEN, GREEN_LIGHT, "Add stock")
            gid = g["id"]
            uid = self.user["id"]
            add_btn.clicked.connect(
                lambda _, gid=gid, sp=add_spin: self._pool_adjust(gid, sp.value(), uid)
            )
            add_l.addWidget(add_spin); add_l.addWidget(add_btn)
            self.pool_table.setCellWidget(row, 2, add_w)

            # Remove Stock widget — same compact treatment.
            rem_w = QWidget(); rem_l = QHBoxLayout(rem_w)
            rem_l.setContentsMargins(4, 2, 4, 2); rem_l.setSpacing(4)
            rem_spin = QSpinBox(); rem_spin.setMinimum(1); rem_spin.setMaximum(9999)
            rem_spin.setValue(1); rem_spin.setFixedHeight(28); rem_spin.setFixedWidth(52)
            rem_spin.setStyleSheet(
                f"QSpinBox{{background:{WHITE};border:1px solid {BORDER};"
                f"border-radius:5px;padding:0 4px;font-size:11px;color:{DARK_CARD};outline:none;}}"
                f"QSpinBox:focus{{border-color:{AMBER};}}"
            )
            rem_btn = _compact_icon_btn("minus", RED, RED_LIGHT, "Remove stock")
            rem_btn.clicked.connect(
                lambda _, gid=gid, sp=rem_spin: self._pool_adjust(gid, -sp.value(), uid)
            )
            rem_l.addWidget(rem_spin); rem_l.addWidget(rem_btn)
            self.pool_table.setCellWidget(row, 3, rem_w)

    def _pool_adjust(self, group_id: int, delta: int, user_id: int):
        reason = "Restock" if delta > 0 else "Correction"
        adjust_variant_group_stock(group_id, delta, reason, user_id)
        self._load_pool_table()
        self._refresh_alert()

    def _search(self):
        self._pg_page   = 0
        self._pg_search = self.search_inp.text().strip()
        self._load_stock_table()

    def _pool_search_fn(self):
        self._pool_search = self.pool_search_inp.text().strip()
        self._load_pool_table()

    def _load_stock_table(self):
        search = self._pg_search
        flt    = self.filter_combo.currentIndex()

        if flt == 2:
            products = [p for p in get_low_stock_products(0) if p["stock"] == 0]
            if search: products = [p for p in products if search.lower() in p["name"].lower()]
            total = len(products); pages = 1
        elif flt == 1:
            products = get_low_stock_products(self._threshold)
            if search: products = [p for p in products if search.lower() in p["name"].lower()]
            total = len(products); pages = 1
        else:
            total    = count_products(search=search, exclude_cases=True)
            pages    = max(1, (total + self._pg_per_page - 1) // self._pg_per_page)
            self._pg_page = min(self._pg_page, pages - 1)
            products = get_products(search=search, exclude_cases=True,
                                    limit=self._pg_per_page,
                                    offset=self._pg_page * self._pg_per_page)

        self.stock_table.setRowCount(0)
        C = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter

        for row, p in enumerate(products):
            self.stock_table.insertRow(row)
            self.stock_table.setRowHeight(row, 38)

            name_item = QTableWidgetItem(p["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.stock_table.setItem(row, 0, name_item)

            grp = QTableWidgetItem(p.get("group_name") or "—")
            grp.setForeground(QColor(MUTED)); grp.setTextAlignment(C)
            self.stock_table.setItem(row, 1, grp)

            stock = p.get("effective_stock", 0)
            color = _stock_color(stock, self._threshold)
            label = "Out" if stock == 0 else (f"{stock} ⚠" if stock <= self._threshold else str(stock))
            si = QTableWidgetItem(label)
            si.setForeground(QColor(color)); si.setTextAlignment(C)
            f = QFont(); f.setBold(True); si.setFont(f)
            self.stock_table.setItem(row, 2, si)

            # Action buttons — Adjust + History
            act = QWidget(); al = QHBoxLayout(act)
            al.setContentsMargins(4, 2, 4, 2); al.setSpacing(4)
            for label, color, text_color, hover_text, cb in [
                ("Adjust",  AMBER, AMBER_TEXT_ON_LIGHT, DARK,
                 lambda _, pid=p["id"], pname=p["name"]: self._open_adjust_dialog(pid, pname)),
                ("History", BLUE,  BLUE, "white",
                 lambda _, pid=p["id"], pname=p["name"]: self._open_history(pid, pname)),
            ]:
                b = QPushButton(label); b.setFixedHeight(26)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                # text_color/hover_text differ per button: AMBER as a
                # background (border/hover fill) is fine, but AMBER as
                # TEXT on white measured ~2.2:1 — same failure pattern
                # found throughout the app. BLUE already passes both ways.
                b.setStyleSheet(
                    f"QPushButton{{background:transparent;color:{text_color};"
                    f"border:1px solid {color};border-radius:5px;"
                    f"font-size:11px;font-weight:600;padding:0 8px;outline:none;}}"
                    f"QPushButton:hover{{background:{color};color:{hover_text};}}"
                    f"QPushButton:pressed{{background:{color};color:{hover_text};border-color:{DARK_CARD};}}"
                )
                b.clicked.connect(cb); al.addWidget(b)
            al.addStretch()
            self.stock_table.setCellWidget(row, 3, act)

        self._pg_label.setText(f"Page {self._pg_page+1} of {pages}  ({total})")
        self._pg_prev.setEnabled(self._pg_page > 0 and flt == 0)
        self._pg_next.setEnabled(self._pg_page < pages - 1 and flt == 0)

    def _open_adjust_dialog(self, product_id: int, product_name: str):
        """Open the pop-up stock-adjustment dialog for a single product —
        mirrors ProductDialog's add/edit pop-up on the Products tab."""
        dlg = StockAdjustDialog(self.user, product_id, product_name, self._threshold, self)
        dlg.exec()
        if dlg.changed:
            self._load_stock_table()
            self._refresh_alert()

    def _on_stock_dbl_click(self, index):
        """Double-clicking a row opens the adjust dialog, same as the
        Products tab's double-click-to-edit behaviour."""
        name_item = self.stock_table.item(index.row(), 0)
        if not name_item: return
        pid = name_item.data(Qt.ItemDataRole.UserRole)
        if pid is not None:
            self._open_adjust_dialog(pid, name_item.text())

    def _open_history(self, product_id: int, product_name: str):
        """Open history dialog directly from the table action button."""
        dlg = HistoryDialog(product_id, product_name, self)
        dlg.exec()

    def _prev_page(self):
        if self._pg_page > 0:
            self._pg_page -= 1; self._load_stock_table()

    def _next_page(self):
        self._pg_page += 1; self._load_stock_table()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _outline_btn(self, text: str) -> QPushButton:
        return _neutral_btn(text, height=34)

    def _section_lbl(self, text: str) -> QLabel:
        l = QLabel(text.upper())
        l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
        return l

    def _table_style(self) -> str:
        return (
            f"QTableWidget{{background:{WHITE};border:none;"
            f"font-size:13px;font-weight:500;}}"
            f"QTableWidget::item{{padding:8px 12px;"
            f"border-bottom:1px solid {BORDER_LIGHT};color:{DARK_CARD};}}"
            f"QTableWidget::item:selected{{background:{AMBER_BG};color:{DARK_CARD};}}"
            f"QHeaderView::section{{background:{DARK_CARD};color:{AMBER};"
            f"font-size:12px;font-weight:700;padding:8px 12px;border:none;"
            f"border-right:1px solid #333;}}"
        )
