"""
ui/supervisor/price_tag_tab.py
Price tag / shelf label designer and printer.
Adapted from the standalone DBF Price Tag Printer — same drawing engine.
"""

from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QCheckBox, QMessageBox,
    QFileDialog,
)
from PyQt6.QtCore import Qt, QRectF, QSizeF, QMarginsF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPageSize, QPageLayout

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_BG, AMBER_LIGHTEST,
    DARK, DARK_4, DARK_CARD,
    WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT, GREEN, GREEN_LIGHT,
)
from core.db_products import get_products, count_products, get_discount_levels
from core.db_config import get as cfg_get, gct_rate
from config import LABEL_DIR

# ── Label / page size catalogue ───────────────────────────────────────────────
_LABEL_SIZES = [
    ("Letter", None, "Letter  (216 × 279 mm)", True),
    ("A4",     None, "A4  (210 × 297 mm)",     True),
    ("Legal",  None, "Legal  (216 × 356 mm)",  True),
]
_PAGE_COLS       = {"A4": 3, "Letter": 3, "Legal": 3}
_PAGE_LABEL_W_MM = 62
_PAGE_LABEL_H_MM = 35


# ── QPainter label drawing (shared with standalone printer) ───────────────────

def _draw_label(painter: QPainter, rect: QRectF,
                product: dict, options: dict, preview: bool = False):
    show_name    = options.get("show_name",    True)
    show_price   = options.get("show_price",   True)
    show_barcode = options.get("show_barcode", False)

    name      = product.get("name", "")
    price     = product.get("price", 0.0)
    barcode   = product.get("barcode", "")
    gct_ok    = product.get("gct_applicable", False)
    disc_rows = product.get("disc_rows", [])

    x = rect.x();  y = rect.y()
    w = rect.width(); h = rect.height()
    w_mm = options.get("label_w_mm", _PAGE_LABEL_W_MM)
    h_mm = options.get("label_h_mm", _PAGE_LABEL_H_MM)
    px_per_mm = w / max(w_mm, 1)

    name_pt    = max(h_mm * 0.38, 14.0)
    price_pt   = 14.0
    gct_pt     = max(h_mm * 0.28, 11.0)
    disc_pt    = max(h_mm * 0.28, 12.0)
    barcode_pt = max(h_mm * 0.18,  8.0)
    pad        = max(2.0 * px_per_mm, 2.0)

    painter.save()
    painter.setClipRect(rect)

    pen_w    = max(0.35 * px_per_mm, 0.8)
    corner_r = max(1.5  * px_per_mm, 3.0) if options.get("rounded_corners", True) else 0
    painter.setPen(QPen(QColor("#000000"), pen_w))
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawRoundedRect(rect.adjusted(pen_w, pen_w, -pen_w, -pen_w), corner_r, corner_r)

    shown_disc  = disc_rows[:options.get("max_disc_rows", 1)]
    disc_h_each = h * 0.12
    disc_h      = disc_h_each * len(shown_disc) if (show_price and shown_disc) else 0
    barcode_h   = (barcode_pt * 0.3528 * 1.6 * px_per_mm) if show_barcode else 0
    name_avail_w = w - pad * 2

    name_font = QFont("Arial"); name_font.setPointSizeF(name_pt); name_font.setBold(True)
    painter.setFont(name_font)

    needed_name_h = painter.boundingRect(
        QRectF(0, 0, name_avail_w, h * 2),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
        name
    ).height() + pad * 0.5 if (show_name and name) else 0

    remaining = h - disc_h - barcode_h - pad * 2
    name_h    = min(needed_name_h, remaining * 0.55) if show_name else 0
    price_h   = remaining - name_h if show_price else 0
    cur_y     = y + pad

    if show_name and name:
        painter.save()
        painter.setClipRect(QRectF(x + pad, cur_y, name_avail_w, name_h))
        painter.setPen(QColor("#000000"))
        painter.drawText(QRectF(x + pad, cur_y, name_avail_w, name_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
            Qt.TextFlag.TextWordWrap, name)
        painter.restore()
        cur_y += name_h

    if show_price:
        price_str = f"${price:.2f}"
        font = QFont("Arial"); font.setPointSizeF(price_pt); font.setBold(True)
        painter.setFont(font); painter.setPen(QColor("#000000"))
        price_px = painter.fontMetrics().horizontalAdvance(price_str)
        painter.drawText(QRectF(x + pad, cur_y, w - pad * 2, price_h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, price_str)
        if gct_ok:
            gf = QFont("Arial"); gf.setPointSizeF(gct_pt); gf.setBold(True)
            painter.setFont(gf); painter.setPen(QColor("#000000"))
            painter.drawText(
                QRectF(x + pad + price_px + pad * 0.4, cur_y + price_h * 0.20,
                       w - pad * 2 - price_px - pad, price_h * 0.65),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "+GCT")
        cur_y += price_h

        for (min_qty, disc_price, pct_str) in shown_disc:
            font = QFont("Arial"); font.setPointSizeF(disc_pt); font.setBold(True)
            painter.setFont(font)
            tr = QRectF(x + pad, cur_y, w - pad * 2, disc_h_each)
            painter.setPen(QColor("#000000"))
            painter.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"BUY {min_qty} GET 1 FOR ${disc_price:.2f}")
            cur_y += disc_h_each

    if show_barcode and barcode:
        bf = QFont("Courier New"); bf.setPointSizeF(barcode_pt)
        painter.setFont(bf); painter.setPen(QColor("#000000"))
        painter.drawText(
            QRectF(x + pad, y + h - barcode_h - pad * 0.5, w - pad * 2, barcode_h),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, barcode)

    painter.restore()


# ── Live preview widget ───────────────────────────────────────────────────────

class _LabelPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._product = None
        self._options = {
            "show_name": True, "show_price": True, "show_barcode": False,
            "max_disc_rows": 1, "rounded_corners": True,
            "label_w_mm": _PAGE_LABEL_W_MM, "label_h_mm": _PAGE_LABEL_H_MM,
        }
        self.setStyleSheet(f"background:{WARM_WHITE};border:1px solid {BORDER};border-radius:8px;")
        self.setMinimumHeight(180)

    def set_product(self, data):  self._product = data; self.update()
    def set_options(self, opts):  self._options = opts;  self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._product:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Select a product to preview")
            return
        wm = self._options.get("label_w_mm", _PAGE_LABEL_W_MM)
        hm = self._options.get("label_h_mm", _PAGE_LABEL_H_MM)
        asp = wm / max(hm, 1)
        mg = 16; aw = self.width() - mg * 2; ah = self.height() - mg * 2
        if aw / asp <= ah: lw = aw; lh = aw / asp
        else:              lh = ah; lw = ah * asp
        lx = (self.width()  - lw) / 2
        ly = (self.height() - lh) / 2
        rect = QRectF(lx, ly, lw, lh)
        painter.setBrush(QBrush(QColor(WHITE)))
        painter.setPen(QPen(QColor(AMBER), 1.5))
        painter.drawRoundedRect(rect, 6, 6)
        _draw_label(painter, rect, self._product, self._options, preview=True)


# ── Main tab widget ───────────────────────────────────────────────────────────

class PriceTagTab(QWidget):

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user          = user
        self._selected     = {}    # pid -> qty
        self._all_prods    = []
        self._prod_data    = {}    # pid -> enriched dict
        self._pg_page      = 0
        self._pg_per_page  = 50
        self._pg_search    = ""
        self.setStyleSheet(f"background:{WARM_WHITE};")
        self._build_ui()
        self._load_table()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8); root.setSpacing(8)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(4)
        split.setStyleSheet(f"QSplitter::handle{{background:{BORDER};}}")
        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setSizes([700, 320])
        root.addWidget(split, stretch=1)

    def _build_left(self):
        card = QFrame()
        card.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        lay = QVBoxLayout(card); lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(8)

        lay.addWidget(self._section_lbl("Products"))

        # Search + clear + refresh
        sb = QHBoxLayout(); sb.setSpacing(4)
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("🔍  Search products…")
        self.search_inp.setFixedHeight(34)
        self.search_inp.setStyleSheet(self._input_style())
        self.search_inp.textChanged.connect(self._search)
        clr_btn = QPushButton("✕"); clr_btn.setFixedSize(34, 34)
        clr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clr_btn.setToolTip("Clear search")
        clr_btn.setStyleSheet(
            f"QPushButton{{background:{BORDER};color:{DARK_CARD};border:none;"
            f"border-radius:7px;font-size:13px;font-weight:700;}}"
            f"QPushButton:hover{{background:{AMBER};color:white;}}")
        clr_btn.clicked.connect(lambda: (self.search_inp.clear(), self.search_inp.setFocus()))
        ref_btn = QPushButton("↻"); ref_btn.setFixedSize(34, 34)
        ref_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ref_btn.setToolTip("Refresh product list")
        ref_btn.setStyleSheet(
            f"QPushButton{{background:{BORDER};color:{DARK_CARD};border:none;"
            f"border-radius:7px;font-size:15px;font-weight:700;}}"
            f"QPushButton:hover{{background:{AMBER};color:white;}}")
        ref_btn.clicked.connect(self._load_table)
        sb.addWidget(self.search_inp, stretch=1)
        sb.addWidget(clr_btn)
        sb.addWidget(ref_btn)
        lay.addLayout(sb)

        self.match_lbl = QLabel("")
        self.match_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;padding-left:2px;")
        lay.addWidget(self.match_lbl)

        # Select all / clear / count
        sel_row = QHBoxLayout(); sel_row.setSpacing(6)
        sel_all = self._outline_btn("☑  Select All"); sel_all.clicked.connect(self._select_all)
        clr     = self._outline_btn("☐  Clear");      clr.clicked.connect(self._clear_selection)
        self.sel_lbl = QLabel("0 selected")
        self.sel_lbl.setStyleSheet(f"color:{AMBER_DARK};font-size:12px;font-weight:600;")
        sel_row.addWidget(sel_all); sel_row.addWidget(clr)
        sel_row.addStretch(); sel_row.addWidget(self.sel_lbl)
        lay.addLayout(sel_row)

        # Product table
        self.prod_table = QTableWidget(); self.prod_table.setColumnCount(5)
        self.prod_table.setHorizontalHeaderLabels(["", "Product", "Price", "Discounts", "Qty"])
        hh = self.prod_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed);         self.prod_table.setColumnWidth(0, 32)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed);         self.prod_table.setColumnWidth(4, 54)
        self.prod_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.prod_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.prod_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.prod_table.verticalHeader().setVisible(False)
        self.prod_table.setShowGrid(False)
        self.prod_table.setAlternatingRowColors(True)
        self.prod_table.setStyleSheet(self._table_style())
        self.prod_table.currentItemChanged.connect(self._on_row_changed)
        self.prod_table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.prod_table, stretch=1)

        # Pagination
        pg = QHBoxLayout(); pg.setSpacing(8)
        self._pg_prev = self._outline_btn("← Prev"); self._pg_prev.setFixedWidth(80)
        self._pg_prev.clicked.connect(self._prev_page)
        self._pg_label = QLabel("Page 1")
        self._pg_label.setStyleSheet(f"color:{MUTED};font-size:11px;")
        self._pg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pg_next = self._outline_btn("Next →"); self._pg_next.setFixedWidth(80)
        self._pg_next.clicked.connect(self._next_page)
        pg.addStretch(); pg.addWidget(self._pg_prev)
        pg.addWidget(self._pg_label); pg.addWidget(self._pg_next); pg.addStretch()
        lay.addLayout(pg)
        return card

    def _build_right(self):
        card = QFrame(); card.setFixedWidth(320)
        card.setStyleSheet(f"background:{WHITE};border-radius:10px;border:1px solid {BORDER};")
        lay = QVBoxLayout(card); lay.setContentsMargins(14, 14, 14, 14); lay.setSpacing(10)

        lay.addWidget(self._section_lbl("Label Preview"))
        self.preview = _LabelPreviewWidget()
        self.preview.setFixedHeight(200)
        lay.addWidget(self.preview)
        lay.addWidget(self._div())

        lay.addWidget(self._section_lbl("Label / Page Size"))
        self.size_combo = QComboBox(); self.size_combo.setFixedHeight(34)
        self.size_combo.setStyleSheet(self._combo_style())
        for entry in _LABEL_SIZES:
            self.size_combo.addItem(entry[2], entry)
        self.size_combo.currentIndexChanged.connect(self._update_preview)
        lay.addWidget(self.size_combo)

        self.cols_row_w = QWidget()
        cr = QHBoxLayout(self.cols_row_w); cr.setContentsMargins(0, 0, 0, 0); cr.setSpacing(8)
        cr.addWidget(self._field_lbl("Labels per Row:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setMinimum(1); self.cols_spin.setMaximum(6); self.cols_spin.setValue(3)
        self.cols_spin.setFixedHeight(32); self.cols_spin.setFixedWidth(60)
        self.cols_spin.setStyleSheet(self._spinbox_style())
        cr.addWidget(self.cols_spin); cr.addStretch()
        lay.addWidget(self.cols_row_w)
        lay.addWidget(self._div())

        lay.addWidget(self._section_lbl("Show on Label"))
        self.chk_name    = self._toggle("Product Name",     True)
        self.chk_price   = self._toggle("Price",             True)
        self.chk_barcode = self._toggle("Barcode (digits)", False)
        self.chk_disc2   = self._toggle("2nd Discount Tier", False)
        self.chk_rounded = self._toggle("Rounded Corners",   True)
        for c in (self.chk_name, self.chk_price, self.chk_barcode,
                  self.chk_disc2, self.chk_rounded):
            c.stateChanged.connect(self._update_preview)
            lay.addWidget(c)
        note = QLabel("  GCT and discount tiers shown automatically when applicable.")
        note.setStyleSheet(f"color:{MUTED};font-size:10px;"); note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{GREEN};font-size:11px;")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.status_lbl)

        self.print_btn = QPushButton("🖨  Preview && Print"); self.print_btn.setFixedHeight(42)
        self.print_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.print_btn.setEnabled(False)
        self.print_btn.setStyleSheet(
            f"QPushButton{{background:{AMBER};color:white;border:none;"
            f"border-radius:8px;font-size:14px;font-weight:700;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};}}"
            f"QPushButton:disabled{{background:{MUTED};color:white;}}")
        self.print_btn.clicked.connect(lambda: self._do_print(False))
        lay.addWidget(self.print_btn)

        self.pdf_btn = QPushButton("💾  Save as PDF"); self.pdf_btn.setFixedHeight(34)
        self.pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.pdf_btn.setEnabled(False)
        self.pdf_btn.setStyleSheet(
            f"QPushButton{{background:{GREEN_LIGHT};color:{GREEN};border:none;"
            f"border-radius:7px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:disabled{{background:{WARM_WHITE};color:{MUTED};}}")
        self.pdf_btn.clicked.connect(lambda: self._do_print(True))
        lay.addWidget(self.pdf_btn)
        return card

    # ── Data ──────────────────────────────────────────────────────────────────

    def _search(self):
        self._pg_page   = 0
        self._pg_search = self.search_inp.text().strip()
        self._load_table()

    def _load_table(self):
        search = self._pg_search
        total  = count_products(search=search, exclude_cases=True)
        pages  = max(1, (total + self._pg_per_page - 1) // self._pg_per_page)
        self._pg_page = min(self._pg_page, pages - 1)

        products = get_products(
            search=search, exclude_cases=True,
            limit=self._pg_per_page,
            offset=self._pg_page * self._pg_per_page,
        )
        self._all_prods = products
        disc_levels = {d["id"]: d for d in get_discount_levels()}
        currency    = cfg_get("currency_symbol", "$")

        tbl = self.prod_table
        tbl.blockSignals(True); tbl.setRowCount(0)

        for row, p in enumerate(products):
            tbl.insertRow(row); tbl.setRowHeight(row, 38)
            pid = p["id"]

            chk = QTableWidgetItem()
            chk.setData(Qt.ItemDataRole.UserRole, pid)
            chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                         Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Checked if pid in self._selected
                              else Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(row, 0, chk)

            ni = QTableWidgetItem(p["name"])
            ni.setData(Qt.ItemDataRole.UserRole + 1, pid)
            tbl.setItem(row, 1, ni)

            pi = QTableWidgetItem(
                f"{currency}{p['selling_price']:.2f}"
                + (" +GCT" if p.get("gct_applicable") else ""))
            pi.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            f = pi.font(); f.setBold(True); pi.setFont(f)
            pi.setForeground(QColor(AMBER_DARK)); tbl.setItem(row, 2, pi)

            # Build disc_rows
            disc_rows = []
            for lvl_key, qty_key, pct_key in [
                ("discount_level1", None, None),
                ("discount_level2", None, None),
                (None, "inline_disc1_qty", "inline_disc1_pct"),
                (None, "inline_disc2_qty", "inline_disc2_pct"),
            ]:
                if lvl_key:
                    lid = p.get(lvl_key)
                    if lid and lid in disc_levels:
                        dl  = disc_levels[lid]
                        qty = dl.get("min_quantity") or 0
                        pct = dl.get("discount_percent") or 0.0
                        if qty and pct:
                            disc_rows.append((qty, round(p["selling_price"]*(1-pct/100), 2),
                                              f"{pct:.0f}%"))
                else:
                    qty = p.get(qty_key); pct = p.get(pct_key)
                    if qty and pct:
                        disc_rows.append((qty, round(p["selling_price"]*(1-pct/100), 2),
                                          f"{pct:.0f}%"))
            seen = set(); deduped = []
            for dr in sorted(disc_rows, key=lambda r: r[0]):
                if dr[0] not in seen: seen.add(dr[0]); deduped.append(dr)
            disc_rows = deduped

            di = QTableWidgetItem(f"{disc_rows[0][0]}+ @ {disc_rows[0][2]}"
                                  if disc_rows else "—")
            di.setForeground(QColor(GREEN) if disc_rows else QColor("#C8C4BC"))
            di.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            tbl.setItem(row, 3, di)

            # Qty spinbox
            qty_spin = QSpinBox(); qty_spin.setMinimum(1); qty_spin.setMaximum(999)
            qty_spin.setValue(self._selected.get(pid, 1))
            qty_spin.setEnabled(pid in self._selected)
            qty_spin.setStyleSheet(
                f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:5px;padding:0 4px;font-size:11px;}}"
                f"QSpinBox:focus{{border-color:{AMBER};}}"
                f"QSpinBox:disabled{{background:{WARM_WHITE};color:{MUTED};}}")
            qty_spin.valueChanged.connect(lambda v, b=pid: self._on_qty_changed(b, v))
            tbl.setCellWidget(row, 4, qty_spin)

            self._prod_data[pid] = {
                "name":           p["name"],
                "barcode":        p.get("barcode", ""),
                "price":          p["selling_price"],
                "gct_applicable": bool(p.get("gct_applicable")),
                "disc_rows":      disc_rows,
            }

        tbl.blockSignals(False)

        q = self.search_inp.text().strip()
        self.match_lbl.setText(
            f"{total:,} match{'es' if total != 1 else ''} for \"{q}\"" if q
            else f"{total:,} products")
        self._pg_label.setText(f"Page {self._pg_page+1} of {pages}  ({total:,})")
        self._pg_prev.setEnabled(self._pg_page > 0)
        self._pg_next.setEnabled(self._pg_page < pages - 1)
        self._update_sel_label()

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() != 0: return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid is None: return
        row  = item.row()
        spin = self.prod_table.cellWidget(row, 4)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected[pid] = spin.value() if spin else 1
            if spin: spin.setEnabled(True)
        else:
            self._selected.pop(pid, None)
            if spin: spin.setEnabled(False)
        self._update_sel_label()

    def _on_qty_changed(self, pid, val):
        if pid in self._selected: self._selected[pid] = val

    def _on_row_changed(self, current, _prev):
        if not current: return
        chk = self.prod_table.item(current.row(), 0)
        if not chk: return
        data = self._prod_data.get(chk.data(Qt.ItemDataRole.UserRole))
        if data: self.preview.set_product(data); self._update_preview()

    def _select_all(self):
        tbl = self.prod_table; tbl.blockSignals(True)
        for row in range(tbl.rowCount()):
            it = tbl.item(row, 0)
            if it:
                pid = it.data(Qt.ItemDataRole.UserRole)
                self._selected[pid] = self._selected.get(pid, 1)
                it.setCheckState(Qt.CheckState.Checked)
                spin = tbl.cellWidget(row, 4)
                if spin: spin.setEnabled(True)
        tbl.blockSignals(False); self._update_sel_label()

    def _clear_selection(self):
        tbl = self.prod_table; tbl.blockSignals(True); self._selected.clear()
        for row in range(tbl.rowCount()):
            it = tbl.item(row, 0)
            if it: it.setCheckState(Qt.CheckState.Unchecked)
            spin = tbl.cellWidget(row, 4)
            if spin: spin.setEnabled(False)
        tbl.blockSignals(False); self._update_sel_label()

    def _update_sel_label(self):
        n     = len(self._selected)
        total = sum(self._selected.values()) if self._selected else 0
        self.sel_lbl.setText(f"{n} selected  ({total} labels)")
        self.print_btn.setEnabled(n > 0); self.pdf_btn.setEnabled(n > 0)

    def _prev_page(self):
        if self._pg_page > 0: self._pg_page -= 1; self._load_table()

    def _next_page(self):
        self._pg_page += 1; self._load_table()

    # ── Preview ───────────────────────────────────────────────────────────────

    def _update_preview(self):
        entry = self.size_combo.currentData()
        if not entry: return
        w_val, h_val, _, is_page = entry
        w_mm = _PAGE_LABEL_W_MM; h_mm = _PAGE_LABEL_H_MM
        self.cols_row_w.setVisible(True)
        self.preview.set_options({
            "show_name":      self.chk_name.isChecked(),
            "show_price":     self.chk_price.isChecked(),
            "show_barcode":   self.chk_barcode.isChecked(),
            "max_disc_rows":  2 if self.chk_disc2.isChecked() else 1,
            "rounded_corners":self.chk_rounded.isChecked(),
            "label_w_mm":     w_mm,
            "label_h_mm":     h_mm,
        })

    # ── Print ─────────────────────────────────────────────────────────────────

    def _do_print(self, save_pdf: bool = False):
        if not self._selected:
            QMessageBox.information(self, "No Products",
                "Select at least one product to print.")
            return

        job = []
        for pid, qty in self._selected.items():
            data = self._prod_data.get(pid)
            if data:
                for _ in range(max(1, qty)): job.append(data)
        if not job: return

        entry = self.size_combo.currentData()
        if not entry: return
        w_val = entry[0]

        opts = {
            "show_name":       self.chk_name.isChecked(),
            "show_price":      self.chk_price.isChecked(),
            "show_barcode":    self.chk_barcode.isChecked(),
            "max_disc_rows":   2 if self.chk_disc2.isChecked() else 1,
            "rounded_corners": self.chk_rounded.isChecked(),
            "label_w_mm":      _PAGE_LABEL_W_MM,
            "label_h_mm":      _PAGE_LABEL_H_MM,
        }

        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrintPreviewDialog
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setColorMode(QPrinter.ColorMode.GrayScale)
            sm = {"A4": QPageSize.PageSizeId.A4,
                  "Letter": QPageSize.PageSizeId.Letter,
                  "Legal":  QPageSize.PageSizeId.Legal}
            printer.setPageLayout(QPageLayout(
                QPageSize(sm.get(str(w_val), QPageSize.PageSizeId.Letter)),
                QPageLayout.Orientation.Portrait,
                QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter))
            cols = self.cols_spin.value()

            if save_pdf:
                # Labels are filed by the date they're printed: labels/<YYYY-MM-DD>/
                date_folder = os.path.join(LABEL_DIR, datetime.now().strftime("%Y-%m-%d"))
                os.makedirs(date_folder, exist_ok=True)
                default_name = f"labels_{datetime.now().strftime('%H%M%S')}.pdf"
                default_path = os.path.join(date_folder, default_name)
                pdf_path, _ = QFileDialog.getSaveFileName(
                    self, "Save Labels as PDF", default_path, "PDF Files (*.pdf)")
                if not pdf_path: return
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(pdf_path)
                self._render(printer, job, cols, opts)
                self.status_lbl.setText(f"✅  Saved {len(job)} label(s) to PDF.")
            else:
                dlg = QPrintPreviewDialog(printer, self)
                dlg.setWindowTitle("Price Tag Preview")
                def _paint(_p=printer, _j=job, _c=cols, _o=opts):
                    self._render(_p, _j, _c, _o)
                dlg.paintRequested.connect(lambda _: _paint())
                dlg.resize(1000, 700); dlg.exec()
                self.status_lbl.setText(f"✅  Sent {len(job)} label(s) to printer.")

        except Exception as e:
            self.status_lbl.setText(f"❌  {e}")
            import traceback; traceback.print_exc()

    def _render(self, printer, job, cols, opts):
        from PyQt6.QtPrintSupport import QPrinter
        painter = QPainter()
        if not painter.begin(printer): return
        try:
            pr       = printer.pageRect(QPrinter.Unit.DevicePixel)
            ppm      = printer.resolution() / 25.4
            lw_px    = _PAGE_LABEL_W_MM * ppm
            lh_px    = _PAGE_LABEL_H_MM * ppm
            gap      = 3 * ppm
            safety   = 3 * ppm
            x0 = pr.left(); y0 = pr.top(); col = 0; ry = y0
            for i, data in enumerate(job):
                _draw_label(painter, QRectF(x0 + col*(lw_px+gap), ry, lw_px, lh_px),
                            data, opts)
                col += 1
                if col >= cols:
                    col = 0; ry += lh_px + gap
                    if ry + lh_px > pr.bottom() - safety and i < len(job) - 1:
                        printer.newPage(); ry = y0
        finally:
            painter.end()

    # ── Style helpers ─────────────────────────────────────────────────────────

    def _outline_btn(self, text):
        b = QPushButton(text); b.setFixedHeight(32)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{LABEL_TEXT};"
            f"border:1.5px solid {BORDER};border-radius:16px;"
            f"font-size:11px;font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}")
        return b

    def _section_lbl(self, text):
        l = QLabel(text.upper())
        l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
        return l

    def _field_lbl(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;")
        return l

    def _toggle(self, label, checked=True):
        cb = QCheckBox(label); cb.setChecked(checked)
        cb.setStyleSheet(
            f"QCheckBox{{color:{DARK_CARD};font-size:12px;}}"
            f"QCheckBox::indicator{{width:15px;height:15px;"
            f"border:1px solid {BORDER};border-radius:3px;background:{WHITE};}}"
            f"QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}")
        return cb

    def _div(self):
        d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
        d.setStyleSheet(f"background:{BORDER_LIGHT};max-height:1px;border:none;")
        return d

    def _input_style(self):
        return (f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:7px;padding:0 10px;font-size:13px;}}"
                f"QLineEdit:focus{{border-color:{AMBER};}}")

    def _combo_style(self):
        return (f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:7px;padding:0 10px;font-size:13px;}}"
                f"QComboBox:focus{{border-color:{AMBER};}}"
                f"QComboBox::drop-down{{border:none;width:20px;}}")

    def _spinbox_style(self):
        return (f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
                f"border-radius:7px;padding:0 8px;font-size:12px;}}"
                f"QSpinBox:focus{{border-color:{AMBER};}}")

    def _table_style(self):
        return (f"QTableWidget{{background:{WHITE};border:none;font-size:13px;color:{DARK_CARD};}}"
                f"QTableWidget{{alternate-background-color:#F0EDE6;}}"
                f"QTableWidget::item{{padding:6px 8px;border-bottom:1px solid {BORDER_LIGHT};}}"
                f"QTableWidget::item:selected{{background:#FEF9EC;color:{DARK_CARD};}}"
                f"QHeaderView::section{{background:{DARK_CARD};color:{AMBER};font-size:11px;"
                f"font-weight:700;padding:6px 8px;border:none;border-right:1px solid #444;}}")
