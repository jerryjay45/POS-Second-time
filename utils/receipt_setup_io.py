"""
Export / import of the receipt + printer setup, so a layout tuned on one PC can
be reproduced exactly on another (or restored after a reinstall).

Safety rules:
  * Only the settings listed in utils.receipt_layout.SPEC can ever be exported
    — nothing else from the settings table (so never database credentials).
  * The Windows printer queue name and the business details are OFF by default:
    queue names differ from PC to PC, and a shared layout shouldn't overwrite
    each store's own name, address or TRN.
  * Import validates EVERYTHING first, shows what would change, and applies it
    in one transaction — all or nothing. Unknown or out-of-range values are
    skipped/reported, never silently applied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from utils.receipt_layout import (HARDWARE_DEFAULTS, SHARED_DEFAULTS, SPEC,
                                  validate_value, setup_code)

FORMAT = "pos-receipt-setup"
VERSION = 1
BUSINESS_KEYS = ("name", "address", "phone", "tax_id", "receipt_footer")


def current_values(get=None) -> dict[str, str]:
    if get is None:
        from core.db_config import get as get
    return {k: get(k, HARDWARE_DEFAULTS.get(k, SHARED_DEFAULTS.get(k, ""))) for k in SPEC}


def export_setup(values: dict[str, str] | None = None, *,
                 include_hardware: bool = True,
                 include_printer_name: bool = False,
                 business: dict | None = None) -> dict:
    vals = values if values is not None else current_values()
    out: dict[str, str] = {}
    for k in SPEC:
        if k in SHARED_DEFAULTS:
            out[k] = validate_value(k, vals.get(k, ""))[1]
        elif include_hardware and (k != "receipt_printer_name" or include_printer_name):
            out[k] = validate_value(k, vals.get(k, ""))[1]
    doc = {"format": FORMAT, "version": VERSION,
           "setup_code": setup_code(vals), "settings": out}
    if business:
        doc["business"] = {k: business.get(k, "") for k in BUSINESS_KEYS}
    return doc


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False)


@dataclass
class ImportPlan:
    changes: list[tuple[str, str, str]] = field(default_factory=list)       # (key, old, new)
    business_changes: list[tuple[str, str, str]] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)            # (key, reason)
    errors: list[str] = field(default_factory=list)                         # fatal problems
    new_settings: dict[str, str] = field(default_factory=dict)
    new_business: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.changes or self.business_changes)


def plan_import(text: str, current: dict[str, str] | None = None,
                current_business: dict | None = None) -> ImportPlan:
    """Parse + validate an exported file. Never touches the database."""
    plan = ImportPlan()
    try:
        doc = json.loads(text)
    except (ValueError, TypeError) as e:
        plan.errors.append(f"This is not a valid setup file ({e}).")
        return plan
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        plan.errors.append("This file is not a receipt setup export.")
        return plan
    ver = doc.get("version")
    if not isinstance(ver, int) or ver > VERSION or ver < 1:
        plan.errors.append(f"Unsupported setup version {ver!r} (this program reads version {VERSION}).")
        return plan
    settings = doc.get("settings")
    if not isinstance(settings, dict):
        plan.errors.append("The file has no settings section.")
        return plan

    cur = current if current is not None else current_values()
    for key, raw in settings.items():
        if key not in SPEC:
            plan.skipped.append((key, "not a setting this version knows"))
            continue
        ok, norm, err = validate_value(key, raw)
        if not ok:
            plan.errors.append(f"{key}: {err}")
            continue
        old = validate_value(key, cur.get(key, ""))[1]
        if norm == old:
            plan.unchanged += 1
        else:
            plan.changes.append((key, old, norm))
            plan.new_settings[key] = norm

    # cross-field sanity: the margin must leave room for text
    merged = {**cur, **plan.new_settings}
    try:
        from utils.receipt_layout import layout_from_values
        cols = layout_from_values(merged).columns
        if int(validate_value("receipt_left_margin", merged.get("receipt_left_margin", "0"))[1] or 0) > cols - 16:
            plan.errors.append("receipt_left_margin: leaves fewer than 16 columns for text")
    except Exception:
        pass

    biz = doc.get("business")
    if biz is not None:
        if not isinstance(biz, dict):
            plan.errors.append("business: must be a set of fields")
        else:
            cb = current_business or {}
            for k in BUSINESS_KEYS:
                if k in biz:
                    v = biz[k]
                    if not isinstance(v, str) or len(v) > 200:
                        plan.errors.append(f"business.{k}: must be text up to 200 characters")
                        continue
                    if v.strip().upper() != str(cb.get(k, "")).strip().upper():
                        plan.business_changes.append((k, str(cb.get(k, "")), v))
                        plan.new_business[k] = v
    return plan


def apply_plan(plan: ImportPlan) -> None:
    """Apply a validated plan atomically. Raises (and changes nothing) on error."""
    if plan.errors:
        raise ValueError("; ".join(plan.errors))
    from core.db_config import apply_setup
    apply_setup(plan.new_settings, plan.new_business or None)
