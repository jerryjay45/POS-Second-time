"""
ui/supervisor/product_dialog.py
Add / edit product — modal dialog.

Replaces the old always-visible right-panel form in the Products tab with a
pop-up, styled to match ui/manager/user_dialog.py: dark header with a title +
close icon, a scrollable white body with labeled fields/sections, and a
footer button row (Delete / Cancel / Save).

Usage:
    dlg = ProductDialog(self.user, self)                        # add
    dlg = ProductDialog(self.user, self, editing_id=pid)         # edit
    if dlg.exec() == QDialog.DialogCode.Accepted:
        self._load_products(self.product_search.text())   # list changed — refresh
"""

import sqlite3

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFrame, QWidget, QMessageBox,
    QScrollArea, QSpinBox, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QDoubleValidator, QPainter, QPen, QIcon, QPixmap

from ui.shared.theme import (
    AMBER, AMBER_DARK, AMBER_LIGHTEST,
    DARK, DARK_CARD, WHITE, WARM_WHITE,
    BORDER, MUTED, LABEL_TEXT, GREEN, RED, RED_LIGHT,
)
from utils.currency import format_currency
from core.db_products import (
    get_product_by_id, add_product, update_product, delete_product,
    get_groups, get_variant_groups, get_variant_group_by_id, add_variant_group,
    update_alias_group, update_variant_group, adjust_variant_group_stock,
    get_discount_levels, cascade_single_cost_to_cases, adjust_stock,
)
from core.db_config import get as cfg_get
from config import DB_PRODUCTS
from ui.shared.checkbox import make_checkbox

# AMBER_DARK (#BA7517) as text measured ~3.7:1 against white — under the
# 4.5:1 WCAG floor for small text. Scoped locally rather than changing
# the shared constant, which is used correctly elsewhere in this file as
# a background/border/accent color.
AMBER_TEXT_ON_LIGHT = "#8a5510"


class ProductDialog(QDialog):
    """Add or edit a single product, as a pop-up (mirrors UserDialog)."""

    def __init__(self, user: dict, parent=None, editing_id: int | None = None):
        super().__init__(parent)
        self.user = user
        self._editing_product_id = editing_id
        self.setModal(True)
        self.setMinimumSize(820, 560)
        self.setMaximumSize(980, 720)
        self.resize(900, 720)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(f"background:{WHITE};")
        self._build_ui()
        if editing_id:
            self._prefill(editing_id)
        else:
            self._reset_form()

    # ================================================================
    # UI SHELL
    # ================================================================

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header
        hdr = QFrame(); hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{DARK};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 0, 18, 0)
        self.title_lbl = QLabel("➕  Add Product")
        self.title_lbl.setStyleSheet("color:white;font-size:14px;font-weight:700;")
        x = QPushButton(); x.setFixedSize(28, 28)
        x.setIcon(self._draw_x_icon("white")); x.setIconSize(QSize(14, 14))
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            "QPushButton{background:transparent;border:none;}"
            "QPushButton:hover{background:rgba(255,255,255,0.12);border-radius:14px;}"
        )
        x.clicked.connect(self.reject)
        hl.addWidget(self.title_lbl); hl.addStretch(); hl.addWidget(x)
        lay.addWidget(hdr)

        # Scrollable body
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{WHITE};border:none;}}")
        fw = QWidget(); fw.setStyleSheet(f"background:{WHITE};")
        flay = QVBoxLayout(fw)
        flay.setContentsMargins(20, 16, 20, 8); flay.setSpacing(8)
        self._build_form(flay)
        scroll.setWidget(fw)
        lay.addWidget(scroll, stretch=1)

        # Footer
        footer = QFrame()
        footer.setStyleSheet(f"background:{WHITE};border-top:1px solid {BORDER};")
        fl = QHBoxLayout(footer); fl.setContentsMargins(20, 12, 20, 12); fl.setSpacing(10)

        self.delete_btn = QPushButton("Delete"); self.delete_btn.setFixedHeight(40)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setStyleSheet(f"""
            QPushButton{{background:{RED_LIGHT};color:{RED};border:none;
            border-radius:20px;font-size:13px;font-weight:600;padding:0 16px;}}
            QPushButton:hover{{background:{RED};color:white;}}
        """)
        self.delete_btn.clicked.connect(self._delete)
        self.delete_btn.setVisible(False)

        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton{{background:{DARK_CARD};color:white;border:none;
            border-radius:20px;font-size:13px;font-weight:600;padding:0 20px;}}
            QPushButton:hover{{background:#444;}}
        """)
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("💾  Save Product"); self.save_btn.setFixedHeight(40)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(self._accent_btn())
        self.save_btn.clicked.connect(self._save)

        fl.addWidget(self.delete_btn)
        fl.addStretch()
        fl.addWidget(self.cancel_btn)
        fl.addWidget(self.save_btn)
        lay.addWidget(footer)

    # ================================================================
    # FORM BODY  (ported from SupervisorWindow._build_product_form)
    # ================================================================

    def _build_form(self, lay: QVBoxLayout):
        def _divider():
            d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
            d.setStyleSheet(f"background:{BORDER};max-height:1px;border:none;")
            return d

        def _section(title):
            l = QLabel(title.upper())
            l.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;letter-spacing:1px;")
            return l

        # ── Top split: Identity+Pricing (left) | Discounts+Flags (right) ─
        top_row = QHBoxLayout(); top_row.setSpacing(24)
        left_col  = QVBoxLayout(); left_col.setSpacing(8)
        right_col = QVBoxLayout(); right_col.setSpacing(8)

        # ── Section 1: Identity (left column) ─────────────────────────
        left_col.addWidget(_section("Identity"))
        self.f_barcode = self._field("Barcode", "Scan or type barcode")
        self.f_name    = self._field("Name",    "e.g. COCA COLA 330ML")
        for lbl, inp in [self.f_barcode, self.f_name]:
            left_col.addWidget(lbl); left_col.addWidget(inp)

        # ── Section 2: Pricing (left column) ──────────────────────────
        left_col.addSpacing(4)
        left_col.addWidget(_divider())
        left_col.addSpacing(2)
        left_col.addWidget(_section("Pricing"))

        self.f_cost = self._field("Cost", "0.00")
        self.f_cost[1].setValidator(QDoubleValidator(0, 999999, 2))
        self.f_cost[1].textChanged.connect(self._calc_selling_price)
        left_col.addWidget(self.f_cost[0]); left_col.addWidget(self.f_cost[1])

        left_col.addWidget(self._flabel("Selling Price"))
        self.f_price = QLineEdit(); self.f_price.setReadOnly(True); self.f_price.setFixedHeight(36)
        self.f_price.setPlaceholderText("Enter a cost above to calculate")
        self.f_price.setStyleSheet(
            f"QLineEdit{{background:#0d1a10;color:{GREEN};border:1px solid #1a3a20;"
            f"border-radius:6px;padding:0 10px;font-size:14px;font-weight:700;}}"
            f"QLineEdit::placeholder{{color:#5c7a68;font-weight:500;}}"
        )
        self.f_price_hint = QLabel(""); self.f_price_hint.setStyleSheet(f"color:{MUTED};font-size:10px;")
        left_col.addWidget(self.f_price); left_col.addWidget(self.f_price_hint)

        left_col.addSpacing(2)
        left_col.addWidget(self._flabel("Product Group"))
        self.f_group = QComboBox(); self.f_group.setStyleSheet(self._combo_style())
        self.f_group.currentIndexChanged.connect(self._calc_selling_price)
        self._populate_groups(); left_col.addWidget(self.f_group)

        grp_row = QHBoxLayout(); grp_row.setSpacing(8)
        alias_col   = QVBoxLayout(); alias_col.setSpacing(4)
        variant_col = QVBoxLayout(); variant_col.setSpacing(4)
        alias_col.addWidget(self._flabel("Alias Group"))
        from ui.shared.searchable_group_combo import SearchableGroupCombo
        self.f_alias_group = SearchableGroupCombo("alias")
        alias_col.addWidget(self.f_alias_group)
        variant_col.addWidget(self._flabel("Variant Group"))
        self.f_variant_group = SearchableGroupCombo("variant")
        variant_col.addWidget(self.f_variant_group)
        grp_row.addLayout(alias_col); grp_row.addLayout(variant_col)
        left_col.addLayout(grp_row)
        left_col.addStretch()

        # ── Section 3: Discounts (right column) ───────────────────────
        right_col.addWidget(_section("Discounts"))
        disc_row = QHBoxLayout(); disc_row.setSpacing(8)
        d1_col = QVBoxLayout(); d1_col.setSpacing(4)
        d2_col = QVBoxLayout(); d2_col.setSpacing(4)

        d1_col.addWidget(self._flabel("Discount Level 1"))
        self.f_disc1 = QComboBox(); self.f_disc1.setStyleSheet(self._combo_style())
        self._populate_discount_levels(self.f_disc1); d1_col.addWidget(self.f_disc1)
        self.f_disc1_custom = self._build_custom_disc_inputs("1")
        self.f_disc1_custom.setVisible(False)
        d1_col.addWidget(self.f_disc1_custom)
        self.f_disc1.currentIndexChanged.connect(
            lambda: self.f_disc1_custom.setVisible(
                self.f_disc1.currentData() == "custom"))

        d2_col.addWidget(self._flabel("Discount Level 2"))
        self.f_disc2 = QComboBox(); self.f_disc2.setStyleSheet(self._combo_style())
        self._populate_discount_levels(self.f_disc2); d2_col.addWidget(self.f_disc2)
        self.f_disc2_custom = self._build_custom_disc_inputs("2")
        self.f_disc2_custom.setVisible(False)
        d2_col.addWidget(self.f_disc2_custom)
        self.f_disc2.currentIndexChanged.connect(
            lambda: self.f_disc2_custom.setVisible(
                self.f_disc2.currentData() == "custom"))

        disc_row.addLayout(d1_col); disc_row.addLayout(d2_col)
        right_col.addLayout(disc_row)

        # ── Section 4: Flags (right column) ───────────────────────────
        right_col.addSpacing(4)
        right_col.addWidget(_divider())
        right_col.addSpacing(2)
        right_col.addWidget(_section("Flags"))
        flags_row = QHBoxLayout(); flags_row.setSpacing(16)
        self.t_gct  = self._toggle("GCT Applicable", True)
        self.t_case = self._toggle("Case Item")
        self.t_case.stateChanged.connect(self._on_case_toggled)
        flags_row.addWidget(self.t_gct); flags_row.addWidget(self.t_case); flags_row.addStretch()
        right_col.addLayout(flags_row)
        right_col.addStretch()

        top_row.addLayout(left_col, stretch=1)
        top_row.addLayout(right_col, stretch=1)
        lay.addLayout(top_row)

        # ── Case Box — shown when "Case Item" is ticked ─────────────
        self.case_box = QFrame(); self.case_box.setVisible(False)
        self.case_box.setStyleSheet(f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};border-radius:6px;")
        cb_lay = QVBoxLayout(self.case_box); cb_lay.setContentsMargins(10,10,10,10); cb_lay.setSpacing(6)

        cb_lay.addWidget(self._flabel("Case Mode"))
        mode_row = QHBoxLayout(); mode_row.setSpacing(16)
        # Styled as checkboxes (matching the rest of the app's checkbox
        # look — a real checkmark glyph, not just a flat color fill) but
        # behave like a two-way radio group: exactly one is always
        # checked, enforced manually below since QCheckBox has no native
        # mutual-exclusivity the way sibling QRadioButtons did.
        self.case_mode_linked  = make_checkbox("Linked to specific product", checked=True)
        self.case_mode_variant = make_checkbox("Linked to a variant group", checked=False)
        for cb in (self.case_mode_linked, self.case_mode_variant):
            mode_row.addWidget(cb)
        mode_row.addStretch()
        cb_lay.addLayout(mode_row)
        self.case_mode_linked.clicked.connect(lambda: self._select_case_mode(True))
        self.case_mode_variant.clicked.connect(lambda: self._select_case_mode(False))

        # ── Mode 1 panel: linked to a specific single product ─────────
        # Split into a selector column (left) and a restock column (right)
        # so it uses the dialog's extra width instead of stacking tall.
        self.case_mode1_frame = QFrame()
        self.case_mode1_frame.setStyleSheet("background:transparent;border:none;")
        m1_outer = QHBoxLayout(self.case_mode1_frame); m1_outer.setContentsMargins(0,4,0,0); m1_outer.setSpacing(20)
        m1_left = QVBoxLayout(); m1_left.setSpacing(6)
        m1_right = QVBoxLayout(); m1_right.setSpacing(6)

        m1_left.addWidget(self._flabel("Parent Single Product"))
        from ui.shared.searchable_product_combo import SearchableProductCombo
        self.f_case_parent = SearchableProductCombo()
        self.f_case_parent.selectionChanged.connect(lambda pid, name: self._on_case_parent_changed())
        m1_left.addWidget(self.f_case_parent)
        self.f_case_cost_hint = QLabel("")
        self.f_case_cost_hint.setStyleSheet(f"color:{MUTED};font-size:10px;")
        m1_left.addWidget(self.f_case_cost_hint)
        m1_left.addWidget(self._flabel("Units per Case"))
        self.f_case_qty = QSpinBox(); self.f_case_qty.setMinimum(1); self.f_case_qty.setMaximum(9999)
        self.f_case_qty.setStyleSheet(self._input_style())
        self.f_case_qty.valueChanged.connect(self._on_case_parent_changed)
        m1_left.addWidget(self.f_case_qty)
        m1_left.addStretch()

        m1_right.addWidget(self._flabel("Restock via Case"))
        self.case_stock_lbl = QLabel("Select a parent product to see stock.")
        self.case_stock_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:11px;font-weight:600;")
        self.case_stock_lbl.setWordWrap(True)
        m1_right.addWidget(self.case_stock_lbl)
        m1_restock_row = QHBoxLayout(); m1_restock_row.setSpacing(6)
        self.case_restock_qty = QSpinBox()
        self.case_restock_qty.setMinimum(1); self.case_restock_qty.setMaximum(9999)
        self.case_restock_qty.setStyleSheet(self._input_style())
        m1_restock_row.addWidget(self.case_restock_qty, stretch=1)
        self.case_restock_add_btn = QPushButton("＋  Add Cases")
        self.case_restock_add_btn.setFixedHeight(30); self.case_restock_add_btn.setEnabled(False)
        self.case_restock_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.case_restock_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};border:1.5px solid {GREEN};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}")
        self.case_restock_add_btn.clicked.connect(self._case_restock_add)
        self.case_restock_remove_btn = QPushButton("−  Remove")
        self.case_restock_remove_btn.setFixedHeight(30); self.case_restock_remove_btn.setEnabled(False)
        self.case_restock_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.case_restock_remove_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1.5px solid {RED};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}")
        self.case_restock_remove_btn.clicked.connect(self._case_restock_remove)
        m1_restock_row.addWidget(self.case_restock_add_btn)
        m1_restock_row.addWidget(self.case_restock_remove_btn)
        m1_right.addLayout(m1_restock_row)
        self.case_restock_feedback = QLabel("")
        self.case_restock_feedback.setStyleSheet(f"font-size:10px;font-weight:600;")
        m1_right.addWidget(self.case_restock_feedback)
        m1_right.addStretch()

        m1_outer.addLayout(m1_left, stretch=1)
        m1_outer.addLayout(m1_right, stretch=1)
        cb_lay.addWidget(self.case_mode1_frame)

        # ── Mode 2 panel: linked to a variant group ─────────────────────
        # Same left/right split as Mode 1: selectors on the left, the
        # restock controls on the right.
        self.case_mode2_frame = QFrame(); self.case_mode2_frame.setVisible(False)
        self.case_mode2_frame.setStyleSheet("background:transparent;border:none;")
        m2_outer = QHBoxLayout(self.case_mode2_frame); m2_outer.setContentsMargins(0,4,0,0); m2_outer.setSpacing(20)
        m2_left = QVBoxLayout(); m2_left.setSpacing(6)
        m2_right = QVBoxLayout(); m2_right.setSpacing(6)

        m2_left.addWidget(self._flabel("Variant Group"))
        m2_grp_row = QHBoxLayout(); m2_grp_row.setSpacing(6)
        self.f_case_variant_group_combo = QComboBox()
        self.f_case_variant_group_combo.setStyleSheet(self._input_style())
        self.f_case_variant_group_combo.setMinimumHeight(32)
        self.f_case_variant_group_combo.currentIndexChanged.connect(self._on_case_variant_group_changed)
        m2_grp_row.addWidget(self.f_case_variant_group_combo, stretch=1)
        new_grp_btn = QPushButton("＋")
        new_grp_btn.setFixedSize(32, 32)
        new_grp_btn.setToolTip("Create a new variant group")
        new_grp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_grp_btn.setStyleSheet(
            f"QPushButton{{background:{AMBER};color:{DARK};border:none;"
            f"border-radius:6px;font-size:16px;font-weight:700;}}"
            f"QPushButton:hover{{background:{AMBER_DARK};color:{DARK};}}")
        new_grp_btn.clicked.connect(self._create_variant_group_inline)
        m2_grp_row.addWidget(new_grp_btn)
        m2_left.addLayout(m2_grp_row)
        self.case_grp_info_lbl = QLabel("")
        self.case_grp_info_lbl.setStyleSheet(f"color:{MUTED};font-size:10px;")
        self.case_grp_info_lbl.setWordWrap(True)
        m2_left.addWidget(self.case_grp_info_lbl)
        m2_left.addWidget(self._flabel("Units per Case (for this product)"))
        self.f_case_qty2 = QSpinBox(); self.f_case_qty2.setMinimum(1); self.f_case_qty2.setMaximum(9999)
        self.f_case_qty2.setStyleSheet(self._input_style())
        self.f_case_qty2.valueChanged.connect(self._on_case_variant_group_changed)
        m2_left.addWidget(self.f_case_qty2)
        m2_left.addStretch()

        m2_right.addWidget(self._flabel("Restock Variant Group Stock"))
        self.pool_stock_lbl = QLabel("Select a variant group to see its stock.")
        self.pool_stock_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:11px;font-weight:600;")
        self.pool_stock_lbl.setWordWrap(True)
        m2_right.addWidget(self.pool_stock_lbl)
        m2_restock_row = QHBoxLayout(); m2_restock_row.setSpacing(6)
        self.pool_restock_qty = QSpinBox()
        self.pool_restock_qty.setMinimum(1); self.pool_restock_qty.setMaximum(9999)
        self.pool_restock_qty.setStyleSheet(self._input_style())
        m2_restock_row.addWidget(self.pool_restock_qty, stretch=1)
        self.pool_restock_add_btn = QPushButton("＋  Add Stock")
        self.pool_restock_add_btn.setFixedHeight(30); self.pool_restock_add_btn.setEnabled(False)
        self.pool_restock_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pool_restock_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};border:1.5px solid {GREEN};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}")
        self.pool_restock_add_btn.clicked.connect(self._case_variant_group_restock_add)
        self.pool_restock_remove_btn = QPushButton("−  Remove")
        self.pool_restock_remove_btn.setFixedHeight(30); self.pool_restock_remove_btn.setEnabled(False)
        self.pool_restock_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pool_restock_remove_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1.5px solid {RED};"
            f"border-radius:6px;font-size:11px;font-weight:700;padding:0 8px;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
            f"QPushButton:disabled{{color:{MUTED};border-color:{BORDER};}}")
        self.pool_restock_remove_btn.clicked.connect(self._case_variant_group_restock_remove)
        m2_restock_row.addWidget(self.pool_restock_add_btn)
        m2_restock_row.addWidget(self.pool_restock_remove_btn)
        m2_right.addLayout(m2_restock_row)
        self.pool_restock_feedback = QLabel("")
        self.pool_restock_feedback.setStyleSheet(f"font-size:10px;font-weight:600;")
        m2_right.addWidget(self.pool_restock_feedback)
        m2_right.addStretch()

        m2_outer.addLayout(m2_left, stretch=1)
        m2_outer.addLayout(m2_right, stretch=1)
        cb_lay.addWidget(self.case_mode2_frame)

        lay.addWidget(self.case_box)

        # ── Section 5: Stock (edit only) ──────────────────────────────
        lay.addSpacing(4)
        lay.addWidget(_divider())
        self.stock_section = QFrame()
        self.stock_section.setVisible(False)
        self.stock_section.setStyleSheet(f"background:transparent;")
        sl = QVBoxLayout(self.stock_section); sl.setContentsMargins(0,0,0,0); sl.setSpacing(6)
        sl.addWidget(_section("Stock Adjustment"))

        self.stock_current_lbl = QLabel("Current stock: —")
        self.stock_current_lbl.setStyleSheet(f"color:{DARK_CARD};font-size:13px;font-weight:600;")
        sl.addWidget(self.stock_current_lbl)

        adj_row = QHBoxLayout(); adj_row.setSpacing(8)
        self.stock_qty = QSpinBox(); self.stock_qty.setMinimum(1); self.stock_qty.setMaximum(99999)
        self.stock_qty.setValue(1); self.stock_qty.setFixedHeight(34)
        self.stock_qty.setStyleSheet(self._input_style())
        self.stock_reason = QComboBox(); self.stock_reason.setFixedHeight(34)
        self.stock_reason.setStyleSheet(self._combo_style())
        for r in ["Restock", "Damaged", "Correction", "Other"]:
            self.stock_reason.addItem(r)
        adj_row.addWidget(self.stock_qty, stretch=1)
        adj_row.addWidget(self.stock_reason, stretch=2)
        sl.addLayout(adj_row)

        stock_btn_row = QHBoxLayout(); stock_btn_row.setSpacing(8)
        self.stock_add_btn = QPushButton("＋  Add Stock"); self.stock_add_btn.setFixedHeight(32)
        self.stock_add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stock_add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{GREEN};border:1.5px solid {GREEN};"
            f"border-radius:7px;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{GREEN};color:white;}}"
        )
        self.stock_add_btn.clicked.connect(self._stock_add)
        self.stock_remove_btn = QPushButton("−  Remove"); self.stock_remove_btn.setFixedHeight(32)
        self.stock_remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stock_remove_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:1.5px solid {RED};"
            f"border-radius:7px;font-size:12px;font-weight:700;}}"
            f"QPushButton:hover{{background:{RED};color:white;}}"
        )
        self.stock_remove_btn.clicked.connect(self._stock_remove)
        stock_btn_row.addWidget(self.stock_add_btn, stretch=1)
        stock_btn_row.addWidget(self.stock_remove_btn, stretch=1)
        sl.addLayout(stock_btn_row)
        lay.addWidget(self.stock_section)

        lay.addStretch()

    # ================================================================
    # DATA — reset / prefill / save / delete
    # ================================================================

    def _reset_form(self):
        self._editing_product_id = None
        self.title_lbl.setText("➕  Add Product")
        self.delete_btn.setVisible(False)
        for _, inp in [self.f_barcode, self.f_name, self.f_cost]:
            inp.clear()
        self.f_group.setCurrentIndex(0)
        self.f_alias_group.clear_value()
        self.f_variant_group.clear_value()
        self.f_disc1.setCurrentIndex(0); self.f_disc2.setCurrentIndex(0)
        self.f_disc1_custom.setVisible(False); self.f_disc2_custom.setVisible(False)
        self.f_disc1_qty.setValue(1); self.f_disc1_pct.setValue(5.0)
        self.f_disc2_qty.setValue(1); self.f_disc2_pct.setValue(10.0)
        self.t_gct.setChecked(True); self.t_case.setChecked(False)
        self.f_price.clear(); self.f_price_hint.clear()
        self.stock_section.setVisible(False)
        self.f_case_parent.clear_value()
        self.f_case_parent.exclude_id(None)
        self.f_case_cost_hint.setText("")
        self.case_restock_qty.setValue(1)
        self.case_restock_feedback.setText("")
        self.case_mode_linked.setChecked(True)
        self.case_mode_variant.setChecked(False)  # no auto-exclusivity now that these are checkboxes, not radios
        self.f_case_qty2.setValue(1)
        self.pool_restock_qty.setValue(1)
        self.pool_restock_feedback.setText("")
        self.case_grp_info_lbl.setText("")
        self.f_group.setEnabled(True)
        self.f_group.setToolTip("")
        self.f_barcode[1].setFocus()

    def _prefill(self, pid: int):
        p = get_product_by_id(pid)
        if not p:
            return
        self._editing_product_id = pid
        self.title_lbl.setText("✎  Edit Product")
        self.delete_btn.setVisible(True)
        self.f_barcode[1].setText(p["barcode"])
        self.f_name[1].setText(p["name"])
        self.f_cost[1].setText(str(p["effective_cost"]))
        self.f_price.setText(f"{format_currency(p['effective_selling_price'])}")
        self.t_gct.setChecked(bool(p["gct_applicable"]))
        self.t_case.setChecked(bool(p["is_case"]))
        if p["is_case"]:
            is_variant_mode = bool(p.get("case_variant_group_id"))
            self.case_mode_linked.setChecked(not is_variant_mode)
            self.case_mode_variant.setChecked(is_variant_mode)
            if is_variant_mode:
                self.f_case_qty2.setValue(p.get("case_qty") or 1)
                self._populate_case_variant_group_combo(select_id=p.get("case_variant_group_id"))
                self.f_group.setEnabled(True)
                self.f_group.setToolTip("")
            else:
                if p.get("case_qty"):
                    self.f_case_qty.setValue(p["case_qty"])
                self._populate_case_parents(select_id=p.get("case_product_id"))
                if p.get("case_product_id"):
                    self.f_group.setEnabled(False)
                    self.f_group.setToolTip(
                        "Group is inherited from the parent single product.\n"
                        "Change the parent to change the group."
                    )
                else:
                    self.f_group.setEnabled(True)
                    self.f_group.setToolTip("")
        for i in range(self.f_group.count()):
            if self.f_group.itemData(i) == p.get("group_id"):
                self.f_group.setCurrentIndex(i); break
        self.f_alias_group.set_value(p.get("alias_group_id"))
        self.f_variant_group.set_value(p.get("variant_group_id"))

        if p.get("inline_discount1_qty") and p.get("inline_discount1_pct"):
            for i in range(self.f_disc1.count()):
                if self.f_disc1.itemData(i) == "custom":
                    self.f_disc1.setCurrentIndex(i); break
            self.f_disc1_qty.setValue(int(p["inline_discount1_qty"]))
            self.f_disc1_pct.setValue(float(p["inline_discount1_pct"]))
            self.f_disc1_custom.setVisible(True)
        else:
            self.f_disc1_custom.setVisible(False)
            for i in range(self.f_disc1.count()):
                if self.f_disc1.itemData(i) == p.get("discount_level1_id"):
                    self.f_disc1.setCurrentIndex(i); break

        if p.get("inline_discount2_qty") and p.get("inline_discount2_pct"):
            for i in range(self.f_disc2.count()):
                if self.f_disc2.itemData(i) == "custom":
                    self.f_disc2.setCurrentIndex(i); break
            self.f_disc2_qty.setValue(int(p["inline_discount2_qty"]))
            self.f_disc2_pct.setValue(float(p["inline_discount2_pct"]))
            self.f_disc2_custom.setVisible(True)
        else:
            self.f_disc2_custom.setVisible(False)
            for i in range(self.f_disc2.count()):
                if self.f_disc2.itemData(i) == p.get("discount_level2_id"):
                    self.f_disc2.setCurrentIndex(i); break

        stock = p.get("effective_stock", 0)
        if p.get("variant_group_id"):
            self.stock_current_lbl.setText(
                f"Current stock: {stock} unit{'s' if stock != 1 else ''}  "
                f"(shared with {p.get('variant_group_name', 'variant group')})"
            )
        else:
            self.stock_current_lbl.setText(f"Current stock: {stock} unit{'s' if stock != 1 else ''}")
        self.stock_qty.setValue(1)
        self.stock_reason.setCurrentIndex(0)
        self.stock_section.setVisible(not p["is_case"])

    def _save(self):
        barcode = self.f_barcode[1].text().strip()
        name    = self.f_name[1].text().strip()
        if not barcode or not name:
            QMessageBox.warning(self, "Missing Fields", "Barcode and Name are required."); return
        try:    cost = float(self.f_cost[1].text() or 0)
        except: QMessageBox.warning(self, "Invalid Cost", "Enter a valid cost."); return
        group_id         = self.f_group.currentData()
        alias_group_id   = self.f_alias_group.selected_id()
        variant_group_id = self.f_variant_group.selected_id()

        is_case             = self.t_case.isChecked()
        is_variant_mode     = is_case and self.case_mode_variant.isChecked()
        case_variant_group_id = self.f_case_variant_group_combo.currentData() if is_variant_mode else None
        case_product_id     = self.f_case_parent.selected_id() if (is_case and not is_variant_mode) else None
        if is_case:
            case_qty = self.f_case_qty2.value() if is_variant_mode else self.f_case_qty.value()
        else:
            case_qty = None

        try:
            case_profit_pct = float(cfg_get("case_profit_pct", "0.10"))
        except (ValueError, TypeError):
            case_profit_pct = 0.10

        if is_case and case_product_id:
            parent = get_product_by_id(case_product_id)
            if parent and parent["cost"] > 0:
                cost = round(parent["cost"] * (case_qty or 1), 4)
                self.f_cost[1].setText(str(cost))
            selling_price = round(cost * (1 + case_profit_pct), 2)
        elif is_variant_mode and case_variant_group_id:
            g = get_variant_group_by_id(case_variant_group_id)
            if g and g["cost"] > 0:
                cost = round(g["cost"] * (case_qty or 1), 4)
                self.f_cost[1].setText(str(cost))
            selling_price = round(cost * (1 + case_profit_pct), 2)
        else:
            selling_price = self._get_selling_price(cost, group_id)

        disc1_id = self.f_disc1.currentData()
        disc2_id = self.f_disc2.currentData()
        if disc1_id == "custom": disc1_id = None
        if disc2_id == "custom": disc2_id = None

        kwargs = dict(
            barcode=barcode, name=name,
            cost=cost, selling_price=selling_price,
            group_id=group_id,
            alias_group_id=alias_group_id,
            variant_group_id=variant_group_id,
            gct_applicable=int(self.t_gct.isChecked()),
            is_case=int(is_case),
            case_qty=case_qty,
            case_product_id=case_product_id,
            case_variant_group_id=case_variant_group_id,
            discount_level1_id=disc1_id,
            discount_level2_id=disc2_id,
        )
        if self.f_disc1.currentData() == "custom":
            kwargs["inline_discount1_qty"] = self.f_disc1_qty.value()
            kwargs["inline_discount1_pct"] = self.f_disc1_pct.value()
        elif self.f_disc1.currentData() is not None:
            kwargs["inline_discount1_qty"] = None
            kwargs["inline_discount1_pct"] = None
        if self.f_disc2.currentData() == "custom":
            kwargs["inline_discount2_qty"] = self.f_disc2_qty.value()
            kwargs["inline_discount2_pct"] = self.f_disc2_pct.value()
        elif self.f_disc2.currentData() is not None:
            kwargs["inline_discount2_qty"] = None
            kwargs["inline_discount2_pct"] = None

        try:
            if self._editing_product_id:
                old = get_product_by_id(self._editing_product_id)
                price_changed = old and round(old["selling_price"], 2) != round(selling_price, 2)
                cost_changed  = old and round(old["cost"], 4) != round(cost, 4)
                update_product(self._editing_product_id, **kwargs)
                if (price_changed or cost_changed) and (alias_group_id or variant_group_id):
                    self._sync_group_members(
                        cost, selling_price, alias_group_id, variant_group_id
                    )
                if cost_changed and not is_case:
                    n = cascade_single_cost_to_cases(self._editing_product_id)
                    if n:
                        QMessageBox.information(
                            self, "Case Prices Updated",
                            f"Cost change cascaded to {n} linked case product{'s' if n != 1 else ''}.\n"
                            f"Case selling prices have been recalculated."
                        )
                QMessageBox.information(self, "Saved", f"'{name}' updated.")
            else:
                add_product(**kwargs)
                QMessageBox.information(self, "Added", f"'{name}' added.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _delete(self):
        if not self._editing_product_id:
            return
        p = get_product_by_id(self._editing_product_id)
        name = p["name"] if p else "this product"
        reply = QMessageBox.question(
            self, "Delete", f"Delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_product(self._editing_product_id)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", str(e))

    def _sync_group_members(self, cost: float, selling_price: float,
                            alias_group_id, variant_group_id):
        """Push an edited cost/price up to the owning group (group is
        authoritative — members defer to it via effective_cost/price)."""
        affected_cases = []
        if alias_group_id:
            affected_cases += update_alias_group(alias_group_id, cost=cost, selling_price=selling_price)
        if variant_group_id:
            affected_cases += update_variant_group(variant_group_id, cost=cost, selling_price=selling_price)

        if affected_cases:
            names = ", ".join(c["name"] for c in affected_cases)
            QMessageBox.information(
                self, "Case Prices Updated",
                f"Cost (${cost:.4f}) and price ({format_currency(selling_price)}) synced to the group.\n"
                f"Linked case product{'s' if len(affected_cases) != 1 else ''} repriced: {names}"
            )

    # ================================================================
    # STOCK ADJUSTMENT (edit only)
    # ================================================================

    def _stock_add(self):
        if not self._editing_product_id: return
        qty    = self.stock_qty.value()
        reason = self.stock_reason.currentText()
        adjust_stock(self._editing_product_id, qty, reason, self.user["id"])
        p = get_product_by_id(self._editing_product_id)
        stock = p["effective_stock"] if p else 0
        self.stock_current_lbl.setText(f"Current stock: {stock} unit{'s' if stock != 1 else ''}")
        self.stock_qty.setValue(1)

    def _stock_remove(self):
        if not self._editing_product_id: return
        qty    = self.stock_qty.value()
        reason = self.stock_reason.currentText()
        adjust_stock(self._editing_product_id, -qty, reason, self.user["id"])
        p = get_product_by_id(self._editing_product_id)
        stock = p["effective_stock"] if p else 0
        self.stock_current_lbl.setText(f"Current stock: {stock} unit{'s' if stock != 1 else ''}")
        self.stock_qty.setValue(1)

    # ================================================================
    # PRICING HELPERS
    # ================================================================

    def _calc_selling_price(self):
        try:    cost = float(self.f_cost[1].text() or 0)
        except: return
        gid = self.f_group.currentData()
        price = self._get_selling_price(cost, gid)
        self.f_price.setText(f"{format_currency(price)}")
        m = self._group_markup(gid)
        self.f_price_hint.setText(f"= {format_currency(cost)} × (1 + {m*100:.0f}%) = {format_currency(price)}" if m and cost else "")

    def _get_selling_price(self, cost, group_id):
        m = self._group_markup(group_id)
        return round(cost * (1 + m), 2) if m and cost else cost

    def _group_markup(self, group_id) -> float:
        if not group_id: return 0.0
        try:
            con = sqlite3.connect(DB_PRODUCTS)
            row = con.execute("SELECT profit_margin FROM groups WHERE id=?", (group_id,)).fetchone()
            con.close(); return float(row[0]) if row and row[0] else 0.0
        except: return 0.0

    # ================================================================
    # CASE TOGGLE + MODE SWITCH
    # ================================================================

    def _on_case_toggled(self, state):
        self.case_box.setVisible(bool(state))
        if bool(state):
            self.f_case_parent.exclude_id(self._editing_product_id)
            self.stock_section.setVisible(False)
            self._populate_case_variant_group_combo()
            self._on_case_mode_changed()
        else:
            self.f_case_parent.clear_value()
            self.f_case_cost_hint.setText("")
            self.f_group.setEnabled(True)
            self.f_group.setToolTip("")
            self.stock_section.setVisible(bool(self._editing_product_id))

    def _select_case_mode(self, linked: bool):
        """Enforce the two case-mode checkboxes as a two-way exclusive
        choice: clicking either one always selects it and deselects the
        other, so the pair can never end up both checked or both
        unchecked — matching what the old QRadioButton pair guaranteed
        automatically, now that they're styled as checkboxes instead."""
        self.case_mode_linked.blockSignals(True)
        self.case_mode_variant.blockSignals(True)
        self.case_mode_linked.setChecked(linked)
        self.case_mode_variant.setChecked(not linked)
        self.case_mode_linked.blockSignals(False)
        self.case_mode_variant.blockSignals(False)
        self._on_case_mode_changed()

    def _on_case_mode_changed(self):
        linked = self.case_mode_linked.isChecked()
        self.case_mode1_frame.setVisible(linked)
        self.case_mode2_frame.setVisible(not linked)
        if linked:
            self._on_case_parent_changed()
        else:
            self._on_case_variant_group_changed()

    # ── Mode 1 helpers ────────────────────────────────────────────────────────

    def _populate_case_parents(self, select_id: int = None):
        self.f_case_parent.exclude_id(self._editing_product_id)
        self.f_case_parent.set_value(select_id)
        self._on_case_parent_changed()

    def _on_case_parent_changed(self):
        parent_id = self.f_case_parent.selected_id()
        qty = self.f_case_qty.value()
        if parent_id is None:
            self.f_case_cost_hint.setText("Cost will be set manually from the Cost field above.")
            self.f_group.setEnabled(True)
            self.f_group.setToolTip("")
        else:
            parent = get_product_by_id(parent_id)
            if parent:
                derived = parent["cost"] * qty
                self.f_case_cost_hint.setText(
                    f"Cost = ${parent['cost']:.4f} × {qty} = ${derived:.4f}  "
                    f"(auto-set on save)"
                )
                parent_group = parent.get("group_id")
                for i in range(self.f_group.count()):
                    if self.f_group.itemData(i) == parent_group:
                        self.f_group.setCurrentIndex(i); break
                self.f_group.setEnabled(False)
                self.f_group.setToolTip(
                    "Group is inherited from the parent single product.\n"
                    "Change the parent to change the group."
                )
            else:
                self.f_case_cost_hint.setText("")
        self._refresh_case_stock_lbl()

    def _refresh_case_stock_lbl(self):
        parent_id = self.f_case_parent.selected_id()
        qty = self.f_case_qty.value() or 1
        if not parent_id:
            self.case_stock_lbl.setText("Select a parent product to see stock.")
            self.case_restock_add_btn.setEnabled(False)
            self.case_restock_remove_btn.setEnabled(False)
            return
        parent = get_product_by_id(parent_id)
        stock = parent["stock"] if parent else 0
        cases_avail = stock // qty
        remainder   = stock % qty
        txt = (f"Parent stock: {stock} unit{'s' if stock != 1 else ''}  →  "
               f"~{cases_avail} case{'s' if cases_avail != 1 else ''} available")
        if remainder:
            txt += f"  (+{remainder} loose unit{'s' if remainder != 1 else ''})"
        self.case_stock_lbl.setText(txt)
        self.case_restock_add_btn.setEnabled(True)
        self.case_restock_remove_btn.setEnabled(True)
        self.case_restock_feedback.setText("")

    def _case_restock_add(self):
        parent_id = self.f_case_parent.selected_id()
        if not parent_id: return
        cases = self.case_restock_qty.value()
        units = cases * (self.f_case_qty.value() or 1)
        adjust_stock(parent_id, units, "Restock (case)", self.user["id"])
        self._refresh_case_stock_lbl()
        self.case_restock_feedback.setStyleSheet(f"color:{GREEN};font-size:10px;font-weight:600;")
        self.case_restock_feedback.setText(
            f"✓  Added {cases} case{'s' if cases != 1 else ''} ({units} units) to parent stock.")

    def _case_restock_remove(self):
        parent_id = self.f_case_parent.selected_id()
        if not parent_id: return
        cases = self.case_restock_qty.value()
        units = cases * (self.f_case_qty.value() or 1)
        adjust_stock(parent_id, -units, "Correction (case)", self.user["id"])
        self._refresh_case_stock_lbl()
        self.case_restock_feedback.setStyleSheet(f"color:{AMBER_TEXT_ON_LIGHT};font-size:10px;font-weight:600;")
        self.case_restock_feedback.setText(
            f"✓  Removed {cases} case{'s' if cases != 1 else ''} ({units} units) from parent stock.")

    # ── Mode 2 helpers (case linked to a variant group) ─────────────────────

    def _populate_case_variant_group_combo(self, select_id: int = None):
        self.f_case_variant_group_combo.blockSignals(True)
        self.f_case_variant_group_combo.clear()
        self.f_case_variant_group_combo.addItem("— Select variant group —", None)
        for g in get_variant_groups():
            self.f_case_variant_group_combo.addItem(g["name"], g["id"])
            if g["id"] == select_id:
                self.f_case_variant_group_combo.setCurrentIndex(
                    self.f_case_variant_group_combo.count() - 1)
        self.f_case_variant_group_combo.blockSignals(False)
        self._on_case_variant_group_changed()

    def _on_case_variant_group_changed(self):
        gid = self.f_case_variant_group_combo.currentData()
        if not gid:
            self.case_grp_info_lbl.setText("")
            self.pool_stock_lbl.setText("Select a variant group to see its stock.")
            self.pool_restock_add_btn.setEnabled(False)
            self.pool_restock_remove_btn.setEnabled(False)
            return
        g = get_variant_group_by_id(gid)
        if not g: return
        qty = self.f_case_qty2.value() or 1
        derived_cost = round(g["cost"] * qty, 4)
        self.case_grp_info_lbl.setText(
            f"Group cost/unit: ${g['cost']:.4f}   Group price/unit: {format_currency(g['selling_price'])}\n"
            f"Case cost = ${g['cost']:.4f} × {qty} = ${derived_cost:.4f}  (auto-set on save)"
        )
        stock = g["stock"]
        self.pool_stock_lbl.setText(
            f"Group stock: {stock} unit{'s' if stock != 1 else ''} available "
            f"(~{stock // qty} case{'s' if stock // qty != 1 else ''})")
        self.pool_restock_add_btn.setEnabled(True)
        self.pool_restock_remove_btn.setEnabled(True)
        self.pool_restock_feedback.setText("")

    def _create_variant_group_inline(self):
        dlg = QDialog(self); dlg.setWindowTitle("New Variant Group")
        dlg.setMinimumWidth(320)
        lay = QVBoxLayout(dlg); lay.setSpacing(10); lay.setContentsMargins(16,16,16,16)
        lay.addWidget(QLabel("Group Name"))
        name_edit = QLineEdit(); name_edit.setPlaceholderText("e.g. SPRITE 330ML VARIANTS")
        name_edit.setStyleSheet(self._input_style()); name_edit.setFixedHeight(34)
        lay.addWidget(name_edit)
        lay.addWidget(QLabel("Cost per Unit ($)"))
        cost_edit = QLineEdit("0.00"); cost_edit.setStyleSheet(self._input_style()); cost_edit.setFixedHeight(34)
        lay.addWidget(cost_edit)
        lay.addWidget(QLabel("Selling Price per Unit ($)"))
        price_edit = QLineEdit("0.00"); price_edit.setStyleSheet(self._input_style()); price_edit.setFixedHeight(34)
        lay.addWidget(price_edit)
        lay.addWidget(QLabel("Starting Stock (units)"))
        stock_spin = QSpinBox(); stock_spin.setMinimum(0); stock_spin.setMaximum(999999)
        stock_spin.setStyleSheet(self._input_style()); stock_spin.setFixedHeight(34)
        lay.addWidget(stock_spin)
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(dlg.reject)
        save_btn   = QPushButton("Create"); save_btn.clicked.connect(dlg.accept)
        save_btn.setStyleSheet(self._accent_btn())
        btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        name = name_edit.text().strip().upper()
        if not name:
            QMessageBox.warning(self, "Required", "Group name is required."); return
        try:
            cost  = float(cost_edit.text() or 0)
            price = float(price_edit.text() or 0)
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Enter valid cost and price values."); return
        try:
            new_id = add_variant_group(
                name, cost=cost, selling_price=price, stock=stock_spin.value()
            )
        except ValueError as e:
            QMessageBox.warning(self, "Name Already Exists", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error Creating Group", str(e))
            return
        self._populate_case_variant_group_combo(select_id=new_id)

    def _case_variant_group_restock_add(self):
        gid = self.f_case_variant_group_combo.currentData()
        if not gid: return
        qty = self.pool_restock_qty.value()
        adjust_variant_group_stock(gid, qty, "Restock", self.user["id"])
        self._on_case_variant_group_changed()
        self.pool_restock_feedback.setStyleSheet(f"color:{GREEN};font-size:10px;font-weight:600;")
        self.pool_restock_feedback.setText(f"✓  Added {qty} unit{'s' if qty != 1 else ''} to group stock.")

    def _case_variant_group_restock_remove(self):
        gid = self.f_case_variant_group_combo.currentData()
        if not gid: return
        qty = self.pool_restock_qty.value()
        adjust_variant_group_stock(gid, -qty, "Correction", self.user["id"])
        self._on_case_variant_group_changed()
        self.pool_restock_feedback.setStyleSheet(f"color:{AMBER_TEXT_ON_LIGHT};font-size:10px;font-weight:600;")
        self.pool_restock_feedback.setText(f"✓  Removed {qty} unit{'s' if qty != 1 else ''} from group stock.")

    # ================================================================
    # GROUPS / DISCOUNT LEVELS
    # ================================================================

    def _populate_groups(self):
        self.f_group.clear(); self.f_group.addItem("— No Group —", None)
        for g in get_groups(): self.f_group.addItem(g["name"], g["id"])

    def _build_custom_disc_inputs(self, tier: str):
        frame = QFrame()
        frame.setStyleSheet(
            f"background:{AMBER_LIGHTEST};border:1px solid {AMBER};"
            f"border-radius:6px;"
        )
        _spinbox_css = (
            f"QSpinBox,QDoubleSpinBox{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};border-radius:7px;"
            f"padding:0 8px;font-size:12px;}}"
            f"QSpinBox:focus,QDoubleSpinBox:focus{{border-color:{AMBER};}}"
        )
        fl = QHBoxLayout(frame); fl.setContentsMargins(8, 6, 8, 6); fl.setSpacing(8)
        fl.addWidget(self._flabel("Min Qty:"))
        qty = QSpinBox(); qty.setMinimum(1); qty.setMaximum(9999)
        qty.setFixedHeight(30); qty.setFixedWidth(70)
        qty.setStyleSheet(_spinbox_css)
        fl.addWidget(qty)
        fl.addWidget(self._flabel("Discount %:"))
        pct = QDoubleSpinBox(); pct.setMinimum(0.1); pct.setMaximum(99.9)
        pct.setDecimals(1); pct.setSuffix("%")
        pct.setFixedHeight(30); pct.setFixedWidth(80)
        pct.setStyleSheet(_spinbox_css)
        fl.addWidget(pct); fl.addStretch()
        setattr(self, f"f_disc{tier}_qty", qty)
        setattr(self, f"f_disc{tier}_pct", pct)
        return frame

    def _populate_discount_levels(self, combo):
        combo.clear(); combo.addItem("— None —", None)
        try:
            for lvl in get_discount_levels():
                combo.addItem(
                    f"{lvl['name']}  ({lvl['percent']*100:.0f}% off, min qty {lvl['min_qty']})",
                    lvl["id"]
                )
        except Exception:
            pass
        combo.addItem("Custom…", "custom")

    # ================================================================
    # STYLE HELPERS  (mirrors SupervisorWindow's, kept local so this
    # dialog has no dependency on the tab it's opened from)
    # ================================================================

    def _field(self, label, placeholder, uppercase=True):
        lbl = self._flabel(label)
        if uppercase:
            inp = QLineEdit(); inp.setPlaceholderText(placeholder); inp.setFixedHeight(34)
            inp.textChanged.connect(
                lambda t, w=inp: w.setText(t.upper()) if t != t.upper() else None
            )
        else:
            inp = QLineEdit(); inp.setPlaceholderText(placeholder); inp.setFixedHeight(34)
        inp.setStyleSheet(self._input_style())
        return lbl, inp

    def _flabel(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{LABEL_TEXT};font-size:11px;font-weight:600;")
        return l

    def _toggle(self, label, checked=False):
        return make_checkbox(label, checked=checked, size=16, font_size=12)

    def _input_style(self, accent=False):
        b = AMBER if accent else BORDER
        return (
            f"QLineEdit{{background:{WHITE};color:{DARK_CARD};border:1px solid {b};"
            f"border-radius:7px;padding:0 10px;font-size:12px;font-weight:400;}}"
            f"QLineEdit:focus{{border-color:{AMBER};background:#fffef9;}}"
            f"QLineEdit::placeholder{{color:{MUTED};}}"
            f"QSpinBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {b};"
            f"border-radius:7px;padding:0 8px;font-size:12px;}}"
            f"QSpinBox:focus{{border-color:{AMBER};}}"
        )

    def _combo_style(self):
        return (
            f"QComboBox{{background:{WHITE};color:{DARK_CARD};border:1px solid {BORDER};"
            f"border-radius:7px;padding:0 10px;font-size:12px;font-weight:400;}}"
            f"QComboBox:focus{{border-color:{AMBER};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
            f"QComboBox::down-arrow{{width:10px;height:10px;}}"
            f"QComboBox QAbstractItemView{{background:{WHITE};color:{DARK_CARD};"
            f"border:1px solid {BORDER};outline:none;"
            f"selection-background-color:{AMBER};selection-color:{DARK};}}"
        )

    def _accent_btn(self):
        return f"QPushButton{{background:{AMBER};color:{DARK};border:none;border-radius:20px;font-size:13px;font-weight:700;padding:0 20px;}}QPushButton:hover{{background:{AMBER_DARK};color:{DARK};}}"

    def _draw_x_icon(self, color: str, size: int = 18) -> QIcon:
        """Hand-painted close icon — no text glyph / font dependency (see
        ui/manager/user_dialog.py for why)."""
        scale = 4
        s = size * scale
        pm = QPixmap(s, s); pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(s * 0.12)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = s * 0.22
        p.drawLine(int(m), int(m), int(s - m), int(s - m))
        p.drawLine(int(s - m), int(m), int(m), int(s - m))
        p.end()
        pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        return QIcon(pm)
