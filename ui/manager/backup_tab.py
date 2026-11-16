"""
ui/manager/backup_tab.py — Manager → Backup.

Destinations, automatic-backup schedule, retention, "Back up now", history and
restore.  All the real work happens in core/backup.py; this file is only the
screen.  Backups run on a background thread so the till never freezes.
"""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QTime, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

import config
from core import backup as bk
from ui.shared.checkbox import make_checkbox
from ui.shared.theme import (
    AMBER, AMBER_DARK, DARK, BORDER, BORDER_LIGHT, MUTED, LABEL_TEXT,
    WARM_WHITE, WHITE, DARK_CARD, RED, GREEN,
)

AMBER_TEXT_ON_WHITE = "#8a5510"     # AMBER itself is too light as text on white


def _btn_css(primary: bool = False) -> str:
    if primary:
        return (f"QPushButton{{background:{AMBER};color:{DARK};border:none;border-radius:17px;"
                f"font-size:12px;font-weight:700;padding:0 16px;}}"
                f"QPushButton:hover{{background:{AMBER_DARK};}}"
                f"QPushButton:disabled{{background:{BORDER_LIGHT};color:{MUTED};}}")
    return (f"QPushButton{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:15px;font-size:12px;font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{border-color:{AMBER};}}"
            f"QPushButton:disabled{{color:{MUTED};}}")


def _table_css() -> str:
    return (f"QTableWidget{{background:{WHITE};border:1px solid {BORDER};border-radius:8px;"
            f"gridline-color:{BORDER_LIGHT};font-size:12px;color:{DARK_CARD};}}"
            f"QHeaderView::section{{background:{WARM_WHITE};color:{LABEL_TEXT};border:none;"
            f"border-bottom:1px solid {BORDER};padding:6px;font-size:11px;font-weight:700;}}")


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _kind_label(kind: str) -> str:
    return {"daily": "Daily", "logout": "Logout", "manual": "Manual",
            "pre-import": "Before import", "pre-restore": "Before restore"}.get(kind, kind)


class BackupTab(QWidget):
    _backup_done = pyqtSignal(dict)          # thread -> UI

    def __init__(self, user: dict, parent=None, limited: bool = False):
        """limited=True is the supervisor view: status, history, Back up now and Test.
        Restore, locations, schedule and retention are manager-only (restore replaces
        all the data), so they are hidden and the handlers refuse as well."""
        super().__init__(parent)
        self.user = user
        self.limited = limited
        self._settings = bk.load_settings()
        self._backup_done.connect(self._on_backup_done)
        self._build_ui()
        self._load_into_ui(self._settings)
        if self.limited:
            self._apply_limited()
        self._clean = self._snapshot()
        self.refresh()
        self._poll = QTimer(self)             # keep the status line fresh while a backup runs
        self._poll.timeout.connect(self._update_busy_state)
        self._poll.start(2000)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:700;background:transparent;")
        return lbl

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text); lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{MUTED};font-size:11px;background:transparent;")
        return lbl

    def _build_ui(self):
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WARM_WHITE};border:none;}}")
        outer.addWidget(scroll)
        body = QWidget(); body.setStyleSheet(f"background:{WARM_WHITE};")
        lay = QVBoxLayout(body); lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(10)
        scroll.setWidget(body)

        self._manager_only = []              # hidden in the supervisor (limited) view
        # status
        self.status_lbl = QLabel(""); self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("font-size:13px;font-weight:700;background:transparent;")
        lay.addWidget(self.status_lbl)
        actions = QHBoxLayout(); actions.setSpacing(8)
        self.now_btn = QPushButton("💾  Back up now"); self.now_btn.setFixedHeight(36)
        self.now_btn.setStyleSheet(_btn_css(True)); self.now_btn.clicked.connect(self._backup_now)
        self.restore_btn = QPushButton("⟲  Restore…"); self.restore_btn.setFixedHeight(36)
        self.restore_btn.setStyleSheet(_btn_css()); self.restore_btn.clicked.connect(self._restore)
        actions.addWidget(self.now_btn); actions.addWidget(self.restore_btn); actions.addStretch()
        self._manager_only.append(self.restore_btn)
        lay.addLayout(actions)

        # destinations
        lay.addWidget(self._hdiv()); lay.addWidget(self._section("Where to save backups"))
        lay.addWidget(self._hint(
            "Each backup is copied to every ticked location. Use a USB drive, another computer "
            "on the shop network, or both, so one failure can't take your data and your backups "
            "together. On Windows a network share is a mapped drive or \\\\SERVER\\share."))
        self.dest_tbl = QTableWidget(0, 3)
        self.dest_tbl.setHorizontalHeaderLabels(["Name", "Folder", "Last check"])
        self.dest_tbl.verticalHeader().setVisible(False)
        self.dest_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dest_tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hdr = self.dest_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.dest_tbl.setFixedHeight(150); self.dest_tbl.setStyleSheet(_table_css())
        lay.addWidget(self.dest_tbl)
        row = QHBoxLayout(); row.setSpacing(8)
        for text, slot in (("➕  Add folder…", self._add_dest), ("Test", self._test_dest),
                           ("Remove", self._remove_dest)):
            b = QPushButton(text); b.setFixedHeight(30); b.setStyleSheet(_btn_css()); b.clicked.connect(slot)
            if text != "Test":
                self._manager_only.append(b)
            row.addWidget(b)
        row.addStretch(); lay.addLayout(row)

        # automatic + retention (manager-only: one box so the supervisor view can hide it)
        self.settings_box = QWidget(); self.settings_box.setStyleSheet("background:transparent;")
        ml = QVBoxLayout(self.settings_box); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(10)
        ml.addWidget(self._hdiv()); ml.addWidget(self._section("Automatic backups"))
        t = QHBoxLayout(); t.setSpacing(10)
        self.daily_cb = make_checkbox("Back up every day at", font_size=12)
        self.daily_time = QTimeEdit(); self.daily_time.setDisplayFormat("hh:mm"); self.daily_time.setFixedHeight(30)
        t.addWidget(self.daily_cb); t.addWidget(self.daily_time)
        t.addWidget(self._hint("If the computer was off then, it runs at the next start-up.")); t.addStretch()
        ml.addLayout(t)
        self.logout_cb = make_checkbox("When a manager or supervisor logs out", font_size=12)
        self.import_cb = make_checkbox("Before every DBF import (the import waits for it)", font_size=12)
        self.files_cb = make_checkbox("Include receipts and price-tag labels", font_size=12)
        for cb in (self.logout_cb, self.import_cb, self.files_cb):
            ml.addWidget(cb)
        ml.addWidget(self._hint("Automatic backups are skipped when nothing has changed since the last one."))

        # retention
        ml.addWidget(self._hdiv()); ml.addWidget(self._section("How many to keep"))
        r = QHBoxLayout(); r.setSpacing(8)
        self.keep_daily = self._spin(1, 365); self.keep_weekly = self._spin(0, 104); self.keep_special = self._spin(1, 100)
        for txt, w in (("Latest", self.keep_daily), ("days, then one per week for", self.keep_weekly),
                       ("weeks.   Before-import / before-restore backups: last", self.keep_special)):
            lb = QLabel(txt); lb.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;background:transparent;")
            r.addWidget(lb); r.addWidget(w)
        r.addStretch(); ml.addLayout(r)
        lay.addWidget(self.settings_box)

        self.feedback = QLabel(""); self.feedback.setStyleSheet(f"color:{GREEN};font-size:11px;font-weight:600;")
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(self.feedback)
        self.save_btn = QPushButton("💾  Save backup settings"); self.save_btn.setFixedHeight(38)
        self.save_btn.setStyleSheet(_btn_css(True)); self.save_btn.clicked.connect(self._save)
        lay.addWidget(self.save_btn)
        self._manager_only += [self.settings_box, self.save_btn]

        # history
        lay.addWidget(self._hdiv()); lay.addWidget(self._section("History"))
        self.hist_tbl = QTableWidget(0, 5)
        self.hist_tbl.setHorizontalHeaderLabels(["When", "Type", "Result", "Size", "Saved to"])
        self.hist_tbl.verticalHeader().setVisible(False)
        self.hist_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hist_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.hist_tbl.horizontalHeader()
        for i in range(4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.hist_tbl.setMinimumHeight(220); self.hist_tbl.setStyleSheet(_table_css())
        lay.addWidget(self.hist_tbl)
        lay.addStretch()

    def _apply_limited(self):
        for w in self._manager_only:
            w.hide()
        for r in range(self.dest_tbl.rowCount()):       # locations: read-only
            it = self.dest_tbl.item(r, 0)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

    def _hdiv(self) -> QFrame:
        f = QFrame(); f.setFixedHeight(1); f.setStyleSheet(f"background:{BORDER};border:none;")
        return f

    def _spin(self, lo: int, hi: int) -> QSpinBox:
        s = QSpinBox(); s.setRange(lo, hi); s.setFixedHeight(30); s.setFixedWidth(70)
        return s

    # ── settings <-> UI ──────────────────────────────────────────────────────

    def _load_into_ui(self, s: dict):
        self.dest_tbl.setRowCount(0)
        for d in s["destinations"]:
            self._add_row(d)
        self.daily_cb.setChecked(bool(s["daily_enabled"]))
        try:
            hh, mm = (int(x) for x in str(s["daily_time"]).split(":")[:2])
        except ValueError:
            hh, mm = 21, 0
        self.daily_time.setTime(QTime(hh, mm))
        self.logout_cb.setChecked(bool(s["on_manager_logout"]))
        self.import_cb.setChecked(bool(s["before_import"]))
        self.files_cb.setChecked(bool(s["include_files"]))
        self.keep_daily.setValue(int(s["keep_daily"]))
        self.keep_weekly.setValue(int(s["keep_weekly"]))
        self.keep_special.setValue(int(s["keep_special"]))

    def _add_row(self, d: dict):
        r = self.dest_tbl.rowCount(); self.dest_tbl.insertRow(r)
        name = QTableWidgetItem(d.get("label") or d["path"])
        name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
        name.setCheckState(Qt.CheckState.Checked if d.get("enabled", True) else Qt.CheckState.Unchecked)
        name.setData(Qt.ItemDataRole.UserRole, d.get("id") or f"d{r}")
        path = QTableWidgetItem(d["path"]); path.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        status = QTableWidgetItem(""); status.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        for c, it in enumerate((name, path, status)):
            self.dest_tbl.setItem(r, c, it)

    def _collect(self) -> dict:
        dests = []
        for r in range(self.dest_tbl.rowCount()):
            n, p = self.dest_tbl.item(r, 0), self.dest_tbl.item(r, 1)
            dests.append({"id": n.data(Qt.ItemDataRole.UserRole), "label": n.text().strip() or p.text(),
                          "path": p.text(), "enabled": n.checkState() == Qt.CheckState.Checked})
        return {"destinations": dests,
                "daily_enabled": self.daily_cb.isChecked(),
                "daily_time": self.daily_time.time().toString("HH:mm"),
                "on_manager_logout": self.logout_cb.isChecked(),
                "before_import": self.import_cb.isChecked(),
                "include_files": self.files_cb.isChecked(),
                "keep_daily": self.keep_daily.value(), "keep_weekly": self.keep_weekly.value(),
                "keep_special": self.keep_special.value()}

    def _snapshot(self):
        s = self._collect()
        return (tuple((d["label"], d["path"], d["enabled"]) for d in s["destinations"]),
                tuple((k, v) for k, v in sorted(s.items()) if k != "destinations"))

    def is_dirty(self) -> bool:
        return self._snapshot() != self._clean

    def _save(self) -> bool:
        if self.limited:
            return False
        s = self._collect()
        if self.daily_cb.isChecked() and not any(d["enabled"] for d in s["destinations"]):
            self._say("Tick at least one location, or switch off the daily backup.", error=True)
            return False
        try:
            bk.save_settings(s)
        except OSError as e:
            self._say(f"Could not save settings: {e}", error=True)
            return False
        self._clean = self._snapshot()
        self._say("✓  Backup settings saved.")
        return True

    def _say(self, text: str, error: bool = False):
        self.feedback.setStyleSheet(f"color:{RED if error else GREEN};font-size:11px;font-weight:600;")
        self.feedback.setText(text)

    # ── destinations ─────────────────────────────────────────────────────────

    def _add_dest(self):
        if self.limited:
            return
        start = os.path.dirname(config.USER_DIR) or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Choose a backup folder", start)
        if not path:
            return
        path = os.path.normpath(path)
        if any(os.path.normcase(self.dest_tbl.item(r, 1).text()) == os.path.normcase(path)
               for r in range(self.dest_tbl.rowCount())):
            self._say("That folder is already in the list.", error=True)
            return
        try:
            inside = os.path.commonpath([os.path.abspath(path), os.path.abspath(config.USER_DIR)]) \
                == os.path.abspath(config.USER_DIR)
        except ValueError:
            inside = False
        if inside and QMessageBox.question(
                self, "Same Folder as Your Data",
                "This folder is inside your program's data folder. A disk failure would take the "
                "backups with the data.\n\nUse it anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._add_row({"label": os.path.basename(path) or path, "path": path, "enabled": True,
                       "id": f"d{int(datetime.now().timestamp())}"})
        self.dest_tbl.selectRow(self.dest_tbl.rowCount() - 1)
        self._test_dest()

    def _selected_row(self) -> int:
        rows = self.dest_tbl.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _test_dest(self):
        r = self._selected_row()
        if r < 0:
            self._say("Select a location first.", error=True)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, msg = bk.test_destination(self.dest_tbl.item(r, 1).text())
        finally:
            QApplication.restoreOverrideCursor()
        item = self.dest_tbl.item(r, 2)
        item.setText(("✓  " if ok else "✗  ") + msg)
        item.setForeground(Qt.GlobalColor.darkGreen if ok else Qt.GlobalColor.red)

    def _remove_dest(self):
        if self.limited:
            return
        r = self._selected_row()
        if r >= 0:
            self.dest_tbl.removeRow(r)

    # ── backup now ───────────────────────────────────────────────────────────

    def _backup_now(self):
        if self.is_dirty() and not self._save():
            return
        if bk.run_async("manual", on_done=self._backup_done.emit) is None:
            self._say("A backup is already running.", error=True)
        self._update_busy_state()

    def _on_backup_done(self, res: dict):
        self.refresh()
        if res.get("busy"):
            return
        if res.get("ok"):
            self._say("✓  Backup complete." + ("  Some locations failed; see History." if res.get("partial") else ""),
                      error=bool(res.get("partial")))
        else:
            self._say("Backup failed: " + str(res.get("error", "unknown error")), error=True)

    def _update_busy_state(self):
        busy = bk.is_running()
        self.now_btn.setEnabled(not busy); self.restore_btn.setEnabled(not busy)
        self.now_btn.setText("Backing up…" if busy else "💾  Back up now")
        if busy:
            self.status_lbl.setText("Backup in progress…")
            self.status_lbl.setStyleSheet(f"color:{AMBER_TEXT_ON_WHITE};font-size:13px;font-weight:700;background:transparent;")
        elif self.status_lbl.text() == "Backup in progress…":
            self.refresh()

    # ── history / status ─────────────────────────────────────────────────────

    def refresh(self):
        last = bk.last_success()
        if not last:
            self.status_lbl.setText("⚠  No backup has been made yet.")
            color = RED
        else:
            age = bk.newest_backup_age_days() or 0
            when = datetime.fromisoformat(last["ts"]).strftime("%d %b %Y  %I:%M %p")
            if age >= 2:
                self.status_lbl.setText(f"⚠  Last backup was {int(age)} days ago ({when}).")
                color = RED
            else:
                self.status_lbl.setText(f"✓  Last backup: {when}")
                color = GREEN
        self.status_lbl.setStyleSheet(f"color:{color};font-size:13px;font-weight:700;background:transparent;")

        log = bk.read_log()[:60]
        self.hist_tbl.setRowCount(len(log))
        for i, e in enumerate(log):
            dests = e.get("destinations") or []
            good = [d for d in dests if d.get("ok")]
            if e.get("skipped"):
                result, color = "Skipped (no changes)", MUTED
            elif e.get("ok") and len(good) < len(dests):
                result, color = f"Partial ({len(good)} of {len(dests)})", AMBER_TEXT_ON_WHITE
            elif e.get("ok"):
                result, color = "OK", GREEN
            else:
                result, color = "Failed", RED
            try:
                when = datetime.fromisoformat(e["ts"]).strftime("%d %b %Y  %I:%M %p")
            except (KeyError, ValueError):
                when = str(e.get("ts", ""))
            cells = [when, _kind_label(e.get("kind", "")), result,
                     _human_size(e["size"]) if e.get("size") else "",
                     ", ".join(d["label"] for d in good)]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 2:
                    it.setForeground(QBrush(QColor(color)))
                errs = [f"{d['label']}: {d.get('error')}" for d in dests if not d.get("ok")]
                if e.get("error"):
                    errs.append(e["error"])
                if errs and c in (2, 4):
                    it.setToolTip("\n".join(errs))
                self.hist_tbl.setItem(i, c, it)

    # ── restore ──────────────────────────────────────────────────────────────

    def _restore(self):
        if self.limited:
            return
        dlg = RestoreDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.chosen:
            return
        path = dlg.chosen
        if QMessageBox.warning(
                self, "Restore Backup",
                "This replaces ALL current products, users, settings and sales with the contents "
                "of the selected backup.\n\nAnything entered since that backup will be lost "
                "(a safety backup of the current data is made first).\n\n"
                "The program will close when the restore finishes.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = bk.restore_backup(path)
        except bk.BackupError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Restore Failed", str(e))
            self.refresh()
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "Restore Complete",
            "The backup was restored.\n\nA safety copy of the previous data was saved as:\n"
            f"{res.get('safety_backup')}\n\nThe program will now close. Start it again to continue.")
        QApplication.exit(0)


class RestoreDialog(QDialog):
    """Pick a backup from the configured locations, or browse for a file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chosen: str | None = None
        self.setWindowTitle("Restore from Backup"); self.setMinimumSize(720, 420)
        self.setStyleSheet(f"QDialog{{background:{WARM_WHITE};}}")
        lay = QVBoxLayout(self); lay.setSpacing(10)
        hint = QLabel("Choose the backup to restore. Newest first. The file is checked before anything is changed.")
        hint.setWordWrap(True); hint.setStyleSheet(f"color:{LABEL_TEXT};font-size:12px;")
        lay.addWidget(hint)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["Made", "Type", "Terminal", "Location", "Size"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        h = self.tbl.horizontalHeader()
        for i in (0, 1, 2, 4):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.setStyleSheet(_table_css()); self.tbl.doubleClicked.connect(self._accept_selected)
        lay.addWidget(self.tbl)
        self._rows: list[dict] = []
        self._fill(bk.list_backups())
        row = QHBoxLayout()
        browse = QPushButton("Browse for a file…"); browse.setFixedHeight(32)
        browse.setStyleSheet(_btn_css()); browse.clicked.connect(self._browse)
        cancel = QPushButton("Cancel"); cancel.setFixedHeight(32); cancel.setStyleSheet(_btn_css())
        cancel.clicked.connect(self.reject)
        go = QPushButton("Restore selected"); go.setFixedHeight(34); go.setStyleSheet(_btn_css(True))
        go.clicked.connect(self._accept_selected)
        row.addWidget(browse); row.addStretch(); row.addWidget(cancel); row.addWidget(go)
        lay.addLayout(row)

    def _fill(self, backups: list[dict]):
        self._rows = backups
        self.tbl.setRowCount(len(backups))
        for i, b in enumerate(backups):
            cells = [b["ts"].strftime("%d %b %Y  %I:%M %p"), _kind_label(b["kind"]), b["tid"],
                     b.get("destination", ""), _human_size(b["size"])]
            for c, text in enumerate(cells):
                self.tbl.setItem(i, c, QTableWidgetItem(text))
        if backups:
            self.tbl.selectRow(0)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a backup file", "", "Backups (*.zip)")
        if path:
            self.chosen = path
            self.accept()

    def _accept_selected(self, *_):
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Restore", "Select a backup first, or browse for a file.")
            return
        self.chosen = self._rows[rows[0].row()]["path"]
        self.accept()
