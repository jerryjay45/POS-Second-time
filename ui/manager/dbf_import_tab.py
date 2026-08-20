"""
ui/manager/dbf_import_tab.py
DBF stock file importer — maps fields from legacy POS DBF exports
to the current products database.

Field mapping:
  descrip   → name
  code      → barcode
  price     → selling_price
  cost      → cost
  gct       → gct_applicable
  group/category → group name (auto-created)
  quantity  → stock (if stock_tracking enabled)
  quan1-3 + pricem1-3 + percent1-3 → discount tiers
  altcode   → stored as alias barcode note
  casecost  → flags product as case item
"""

from __future__ import annotations
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QComboBox, QProgressBar,
    QCheckBox, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST, AMBER_BG,
    DARK, DARK_4, DARK_CARD,
    WHITE, WARM_WHITE, BORDER, BORDER_LIGHT,
    MUTED, LABEL_TEXT,
    RED, RED_LIGHT, GREEN, GREEN_LIGHT, GREEN_BORDER,
)


# ── Import worker (runs in background thread) ─────────────────────────────────

class _ImportWorker(QThread):
    progress  = pyqtSignal(int, int)        # (done, total)
    row_done  = pyqtSignal(dict)            # per-row result dict
    finished  = pyqtSignal(dict)            # summary dict
    error     = pyqtSignal(str)

    def __init__(self, filepath: str, options: dict, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.options  = options

    def run(self):
        try:
            from dbfread import DBF
        except ImportError:
            self.error.emit(
                "dbfread is not installed.\n"
                "Run:  pip install dbfread --break-system-packages"
            )
            return

        try:
            table = DBF(self.filepath, lowernames=True, ignore_missing_memofile=True)
            records = list(table)
        except Exception as e:
            self.error.emit(f"Could not read DBF file:\n{e}")
            return

        opts = self.options
        total   = len(records)
        created = 0
        updated = 0
        skipped = 0
        errors  = 0

        from core.db_products import (
            get_product_by_barcode, add_product, update_product,
            get_groups, add_group, _conn as products_conn,
        )
        from core.db_config import get_bool, get as cfg_get

        track_stock = get_bool("stock_tracking", False)

        # ── Group cache ───────────────────────────────────────────────
        group_cache = {g["name"].upper(): g["id"] for g in get_groups()}

        def _get_or_create_group(name: str) -> int | None:
            if not name or not name.strip():
                return None
            key = name.strip().upper()
            if key not in group_cache:
                new_id = add_group(key)
                if new_id:
                    group_cache[key] = new_id
            return group_cache.get(key)


        # ── Detect which discount fields this DBF has ─────────────────
        # DBF files from different POS versions may omit percent1/2/3
        # (only have quan + pricem) or omit all discount fields entirely.
        sample_fields = set(records[0].keys()) if records else set()
        has_percent   = "percent1" in sample_fields
        has_pricem    = "pricem1"  in sample_fields
        has_quan      = "quan1"    in sample_fields
        # A DBF has usable discount data only if it has quantities AND
        # at least one of: percent fields or fixed-price fields.
        dbf_has_discounts = has_quan and (has_percent or has_pricem)

        # ── Main import loop ──────────────────────────────────────────
        for i, rec in enumerate(records):
            self.progress.emit(i + 1, total)
            r = dict(rec)

            name    = (r.get("descrip") or "").strip()
            barcode = str(r.get("code") or "").strip()

            if not name or not barcode:
                skipped += 1
                self.row_done.emit({"name": name or "—", "barcode": barcode,
                                    "status": "skipped", "reason": "Missing name or barcode"})
                continue

            price = float(r.get("price") or r.get("priceg") or 0)
            cost  = float(r.get("cost") or 0)
            gct   = bool(r.get("gct", False))

            # Group
            group_raw = (r.get("group") or r.get("category") or "").strip()
            group_id  = _get_or_create_group(group_raw) if opts.get("import_groups") else None

            # Inline discount tiers — stored directly on the product row,
            # no global discount_level entries created so the edit form stays clean.
            inline_disc1_qty = inline_disc1_pct = None
            inline_disc2_qty = inline_disc2_pct = None
            disc_source = ""   # for the import log note
            if opts.get("import_discounts") and dbf_has_discounts:
                for tier, qty_key, pct_key, pm_key in [
                    (1, "quan1", "percent1", "pricem1"),
                    (2, "quan2", "percent2", "pricem2"),
                ]:
                    qty = int(round(float(r.get(qty_key) or 0)))
                    if qty <= 0:
                        continue

                    pct = 0.0
                    if has_percent:
                        pct = float(r.get(pct_key) or 0)

                    # Fall back to pricem (fixed discounted price) when
                    # percent field is absent or zero but pricem is set.
                    if pct <= 0 and has_pricem and price > 0:
                        pm = float(r.get(pm_key) or 0)
                        if 0 < pm < price:
                            pct = round((1 - pm / price) * 100, 1)

                    if pct > 0:
                        if tier == 1:
                            inline_disc1_qty, inline_disc1_pct = qty, round(pct, 1)
                            disc_source += f"L1:{qty}+@{pct:.1f}% "
                        else:
                            inline_disc2_qty, inline_disc2_pct = qty, round(pct, 1)
                            disc_source += f"L2:{qty}+@{pct:.1f}% "

            existing = get_product_by_barcode(barcode)

            kwargs = {}
            if opts.get("import_price"):
                kwargs["selling_price"] = price
            if opts.get("import_cost") and cost > 0:
                kwargs["cost"] = cost
            if opts.get("import_gct"):
                kwargs["gct_applicable"] = int(gct)
            if opts.get("import_groups") and group_id:
                kwargs["group_id"] = group_id
            if opts.get("import_discounts") and dbf_has_discounts:
                # Only overwrite inline discount fields when this DBF
                # actually supplied discount data for this product row.
                # If both are None the DBF had no discount info — leave
                # any existing values in the DB untouched.
                if inline_disc1_qty is not None:
                    kwargs["inline_disc1_qty"] = inline_disc1_qty
                    kwargs["inline_disc1_pct"] = inline_disc1_pct
                if inline_disc2_qty is not None:
                    kwargs["inline_disc2_qty"] = inline_disc2_qty
                    kwargs["inline_disc2_pct"] = inline_disc2_pct

            try:
                if existing:
                    if opts.get("update_existing"):
                        if not opts.get("preserve_names"):
                            kwargs["name"] = name
                        update_product(existing["id"], **kwargs)
                        if track_stock and opts.get("import_stock"):
                            qty = float(r.get("quantity") or 0)
                            if qty != 0:
                                from core.db_products import adjust_stock
                                adjust_stock(existing["id"], int(qty),
                                             "DBF import", user_id=None)
                        updated += 1
                        disc_note = disc_source.strip() if opts.get("import_discounts") and disc_source else ""
                        self.row_done.emit({"name": name, "barcode": barcode,
                                            "status": "updated", "reason": disc_note})
                    else:
                        skipped += 1
                        self.row_done.emit({"name": name, "barcode": barcode,
                                            "status": "skipped",
                                            "reason": "Already exists (update disabled)"})
                else:
                    if opts.get("create_new"):
                        new_id = add_product(
                            barcode=barcode,
                            name=name,
                            cost=cost,
                            selling_price=price,
                            group_id=group_id,
                            gct_applicable=int(gct),
                            inline_disc1_qty=inline_disc1_qty,
                            inline_disc1_pct=inline_disc1_pct,
                            inline_disc2_qty=inline_disc2_qty,
                            inline_disc2_pct=inline_disc2_pct,
                        )
                        if new_id and track_stock and opts.get("import_stock"):
                            qty = float(r.get("quantity") or 0)
                            if qty > 0:
                                from core.db_products import adjust_stock
                                adjust_stock(new_id, int(qty), "DBF import", user_id=None)
                        created += 1
                        self.row_done.emit({"name": name, "barcode": barcode,
                                            "status": "created", "reason": ""})
                    else:
                        skipped += 1
                        self.row_done.emit({"name": name, "barcode": barcode,
                                            "status": "skipped",
                                            "reason": "New product (create disabled)"})
            except Exception as e:
                errors += 1
                self.row_done.emit({"name": name, "barcode": barcode,
                                    "status": "error", "reason": str(e)})

        self.finished.emit({
            "total":   total,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors":  errors,
        })


# ── DBFImportTab ──────────────────────────────────────────────────────────────

class DBFImportTab(QWidget):

    import_complete = pyqtSignal()   # emitted after a successful import

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self.user    = user
        self._worker = None
        self._file   = ""
        self.setStyleSheet(f"background:{WARM_WHITE};")
        self._build()
        self._load_remembered_folder()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ── File picker ───────────────────────────────────────────────
        root.addWidget(self._section("Source File"))

        file_row = QHBoxLayout(); file_row.setSpacing(8)
        self.file_lbl = QLineEdit()
        self.file_lbl.setPlaceholderText("No file selected…")
        self.file_lbl.setReadOnly(True)
        self.file_lbl.setFixedHeight(36)
        self.file_lbl.setStyleSheet(
            f"QLineEdit{{background:{WHITE};color:{MUTED};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;}}"
        )
        browse = self._accent_btn("📂  Select Folder")
        browse.setFixedWidth(120)
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.file_lbl, stretch=1)
        file_row.addWidget(browse)
        root.addLayout(file_row)

        # File info label
        self.file_info = QLabel("")
        self.file_info.setStyleSheet(f"color:{MUTED};font-size:11px;")
        root.addWidget(self.file_info)

        root.addWidget(self._div())

        # ── Import options ────────────────────────────────────────────
        root.addWidget(self._section("What to Import"))

        opts_frame = QFrame()
        opts_frame.setStyleSheet(
            f"background:{WHITE};border:1px solid {BORDER};border-radius:8px;"
        )
        of = QHBoxLayout(opts_frame)
        of.setContentsMargins(16, 12, 16, 12); of.setSpacing(24)

        left_opts  = QVBoxLayout(); left_opts.setSpacing(6)
        right_opts = QVBoxLayout(); right_opts.setSpacing(6)

        self.chk_price     = self._chk("Selling Price  (price field)", True)
        self.chk_cost      = self._chk("Cost  (cost field)", True)
        self.chk_gct       = self._chk("GCT Flag  (gct field)", True)
        self.chk_groups    = self._chk("Groups / Categories  (group/category fields)", True)
        self.chk_discounts = self._chk("Discount Levels  (quan1-3 / percent1-3 or pricem1-3 fields)", True)
        self.chk_stock     = self._chk("Stock Quantity  (quantity field)", False)

        for c in (self.chk_price, self.chk_cost, self.chk_gct):
            left_opts.addWidget(c)
        for c in (self.chk_groups, self.chk_discounts, self.chk_stock):
            right_opts.addWidget(c)
        right_opts.addStretch()

        of.addLayout(left_opts); of.addLayout(right_opts); of.addStretch()
        root.addWidget(opts_frame)

        root.addWidget(self._section("Conflict Resolution"))

        conflict_frame = QFrame()
        conflict_frame.setStyleSheet(
            f"background:{WHITE};border:1px solid {BORDER};border-radius:8px;"
        )
        cf = QHBoxLayout(conflict_frame)
        cf.setContentsMargins(16, 12, 16, 12); cf.setSpacing(24)

        self.chk_create = self._chk("Create new products not in database", True)
        self.chk_update = self._chk("Update existing products (matched by barcode)", True)
        self.chk_preserve_names = self._chk("Don't overwrite existing product names", False)

        hint = QLabel("Products are matched by barcode. Unmatched barcodes are skipped if 'Create new' is off.")
        hint.setStyleSheet(f"color:{MUTED};font-size:10px;")
        hint.setWordWrap(True)

        cv = QVBoxLayout(); cv.setSpacing(6)
        ch = QHBoxLayout(); ch.setSpacing(24)
        ch.addWidget(self.chk_create); ch.addWidget(self.chk_update); ch.addStretch()
        cv.addLayout(ch)
        cv.addWidget(self.chk_preserve_names)
        cv.addWidget(hint)
        cf.addLayout(cv)
        root.addWidget(conflict_frame)

        root.addWidget(self._div())

        # ── Progress + run ────────────────────────────────────────────
        run_row = QHBoxLayout(); run_row.setSpacing(10)
        self.import_btn = self._accent_btn("▶  Start Import")
        self.import_btn.setFixedHeight(40)
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._start_import)
        self.cancel_btn = self._outline_btn("■  Cancel")
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_import)
        run_row.addWidget(self.import_btn, stretch=1)
        run_row.addWidget(self.cancel_btn)
        root.addLayout(run_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            f"QProgressBar{{background:{BORDER};border-radius:4px;border:none;}}"
            f"QProgressBar::chunk{{background:{AMBER};border-radius:4px;}}"
        )
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        root.addWidget(self.status_lbl)

        root.addWidget(self._div())

        # ── Results table ─────────────────────────────────────────────
        root.addWidget(self._section("Import Log"))

        self.results_tbl = QTableWidget()
        self.results_tbl.setColumnCount(4)
        self.results_tbl.setHorizontalHeaderLabels(["Barcode", "Product Name", "Status", "Note"])
        hh = self.results_tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.results_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.results_tbl.verticalHeader().setVisible(False)
        self.results_tbl.setShowGrid(False)
        self.results_tbl.setAlternatingRowColors(True)
        self.results_tbl.setStyleSheet(
            f"QTableWidget{{background:{WHITE};border:none;font-size:11px;color:{DARK_CARD};}}"
            f"QTableWidget::item{{padding:4px 8px;border-bottom:1px solid {BORDER_LIGHT};}}"
            f"QTableWidget::item:selected{{background:{AMBER_BG};}}"
            f"QHeaderView::section{{background:{DARK};color:{AMBER};font-size:10px;"
            f"font-weight:700;padding:5px 8px;border:none;border-right:1px solid {DARK_4};}}"
            f"QTableWidget{{alternate-background-color:{WARM_WHITE};}}"
        )
        root.addWidget(self.results_tbl, stretch=1)

        # Summary bar
        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet(
            f"color:{DARK_CARD};font-size:12px;font-weight:600;"
            f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};"
            f"border-radius:6px;padding:8px 12px;"
        )
        self.summary_lbl.setVisible(False)
        root.addWidget(self.summary_lbl)

    # ── File browsing ─────────────────────────────────────────────────────────

    def _find_stock_dbf(self, folder: str) -> str | None:
        """Return path to stock.dbf in folder, case-insensitive, or None."""
        try:
            for entry in os.scandir(folder):
                if entry.name.lower() == "stock.dbf" and entry.is_file():
                    return entry.path
        except OSError:
            pass
        return None

    def _load_remembered_folder(self):
        """On init, check if the saved folder still has stock.dbf and pre-load it."""
        try:
            from core.db_config import get as cfg_get
            folder = cfg_get("dbf_import_folder", "")
            if folder and os.path.isdir(folder):
                path = self._find_stock_dbf(folder)
                if path:
                    self._set_file(path)
        except Exception:
            pass

    def _browse(self):
        # Start in the last-used folder if it still exists
        try:
            from core.db_config import get as cfg_get
            start = cfg_get("dbf_import_folder", "")
            if not start or not os.path.isdir(start):
                start = ""
        except Exception:
            start = ""

        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder Containing stock.dbf", start
        )
        if not folder:
            return

        path = self._find_stock_dbf(folder)
        if not path:
            self.file_info.setText("⚠  No stock.dbf found in that folder.")
            self.file_info.setStyleSheet(f"color:{RED};font-size:11px;")
            return

        # Save folder for next time
        try:
            from core.db_config import set as cfg_set
            cfg_set("dbf_import_folder", folder)
        except Exception:
            pass

        self._set_file(path)

    def _set_file(self, path: str):
        """Load a DBF file path into the UI."""
        self._file = path
        self.file_lbl.setText(path)
        self.file_lbl.setStyleSheet(
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {AMBER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;}}"
        )
        try:
            from dbfread import DBF
            table = DBF(path, lowernames=True, ignore_missing_memofile=True)
            count = len(list(table))
            self.file_info.setText(
                f"✓  {count:,} records found  ·  {os.path.getsize(path):,} bytes"
            )
            self.file_info.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
            self.import_btn.setEnabled(True)
        except ImportError:
            self.file_info.setText("⚠  dbfread not installed — run: pip install dbfread --break-system-packages")
            self.file_info.setStyleSheet(f"color:{RED};font-size:11px;")
        except Exception as e:
            self.file_info.setText(f"⚠  Could not read file: {e}")
            self.file_info.setStyleSheet(f"color:{RED};font-size:11px;")

    # ── Import ────────────────────────────────────────────────────────────────

    def _start_import(self):
        if not self._file:
            return

        self.results_tbl.setRowCount(0)
        self.summary_lbl.setVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.import_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_lbl.setText("Importing…")

        options = {
            "import_price":    self.chk_price.isChecked(),
            "import_cost":     self.chk_cost.isChecked(),
            "import_gct":      self.chk_gct.isChecked(),
            "import_groups":   self.chk_groups.isChecked(),
            "import_discounts":self.chk_discounts.isChecked(),
            "import_stock":    self.chk_stock.isChecked(),
            "create_new":      self.chk_create.isChecked(),
            "update_existing": self.chk_update.isChecked(),
            "preserve_names":  self.chk_preserve_names.isChecked(),
        }

        self._worker = _ImportWorker(self._file, options, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.row_done.connect(self._on_row_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _cancel_import(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self.status_lbl.setText("Import cancelled.")
            self._reset_buttons()

    def _on_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.status_lbl.setText(f"Processing {done:,} / {total:,}…")

    def _on_row_done(self, result: dict):
        STATUS_COLORS = {
            "created": GREEN,
            "updated": AMBER,
            "skipped": MUTED,
            "error":   RED,
        }
        STATUS_BG = {
            "created": "#F0FFF4",
            "updated": "#FFFBE6",
            "skipped": None,
            "error":   "#FFF0F0",
        }
        s      = result["status"]
        color  = STATUS_COLORS.get(s, MUTED)
        bg     = STATUS_BG.get(s)
        row    = self.results_tbl.rowCount()
        self.results_tbl.insertRow(row)
        self.results_tbl.setRowHeight(row, 26)

        for col, text in enumerate([
            result.get("barcode", ""),
            result.get("name", ""),
            s.capitalize(),
            result.get("reason", ""),
        ]):
            it = QTableWidgetItem(text)
            it.setForeground(QColor(color))
            if bg:
                it.setBackground(QColor(bg))
            self.results_tbl.setItem(row, col, it)

        # Auto-scroll to latest
        self.results_tbl.scrollToBottom()

    def _on_finished(self, summary: dict):
        self._reset_buttons()
        self.progress_bar.setVisible(False)

        t = summary
        msg = (
            f"✓  Import complete  —  "
            f"Created: {t['created']}   "
            f"Updated: {t['updated']}   "
            f"Skipped: {t['skipped']}   "
            f"Errors: {t['errors']}   "
            f"Total: {t['total']}"
        )
        self.summary_lbl.setText(msg)
        self.summary_lbl.setVisible(True)
        self.status_lbl.setText("")
        self.import_complete.emit()

    def _on_error(self, msg: str):
        self._reset_buttons()
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "Import Error", msg)
        self.status_lbl.setText(f"Error: {msg.split(chr(10))[0]}")

    def _reset_buttons(self):
        self.import_btn.setEnabled(bool(self._file))
        self.cancel_btn.setEnabled(False)

    # ── Style helpers ─────────────────────────────────────────────────────────

    def _section(self, text: str) -> QLabel:
        l = QLabel(text.upper())
        l.setStyleSheet(
            f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;"
        )
        return l

    def _div(self) -> QFrame:
        d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
        d.setStyleSheet(f"background:{BORDER_LIGHT};max-height:1px;border:none;")
        return d

    def _chk(self, label: str, checked: bool = True) -> QCheckBox:
        cb = QCheckBox(label); cb.setChecked(checked)
        cb.setStyleSheet(
            f"QCheckBox{{color:{DARK_CARD};font-size:12px;}}"
            f"QCheckBox::indicator{{width:15px;height:15px;"
            f"border:1px solid {BORDER};border-radius:3px;background:{WHITE};}}"
            f"QCheckBox::indicator:checked{{background:{AMBER};border-color:{AMBER};}}"
        )
        return cb

    def _accent_btn(self, text: str) -> QPushButton:
        b = QPushButton(text); b.setFixedHeight(34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{AMBER};color:white;border:none;"
            f"border-radius:8px;font-size:12px;font-weight:600;padding:0 16px;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};}}"
            f"QPushButton:disabled{{background:{MUTED};color:#aaa;}}"
        )
        return b

    def _outline_btn(self, text: str) -> QPushButton:
        b = QPushButton(text); b.setFixedHeight(34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{LABEL_TEXT};"
            f"border:1.5px solid {BORDER};border-radius:8px;"
            f"font-size:12px;font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{border-color:{AMBER};color:{AMBER};}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER_LIGHT};}}"
        )
        return b
