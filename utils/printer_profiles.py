"""
Starting points for common receipt printers.

A profile only sets the HARDWARE settings that differ between printer types
(never the Windows queue name — that is different on every PC). Pick one to get
sensible values, then run the calibration wizard to fine-tune the two numbers a
profile can only estimate: how many columns really fit, and how many blank lines
are needed to push a receipt past the tear bar.
"""
from __future__ import annotations

PROFILES: list[dict] = [
    {
        "id": "epson_tm_u220",
        "name": "Epson TM-U220 (dot matrix, 76 mm, tear-off)",
        "description": "Impact printer on roll paper, no cutter. Plain-text raw mode, "
                       "no form feed. Feed lines are an estimate — run the calibration wizard.",
        "values": {
            "receipt_printer_mode": "raw", "receipt_paper_width_mm": "76",
            "receipt_columns": "", "receipt_left_margin": "0",
            "receipt_feed_lines": "5", "receipt_form_feed": "0",
            "receipt_printer_escpos": "0", "receipt_printer_has_cutter": "0",
        },
    },
    {
        "id": "thermal_58",
        "name": "Thermal 58 mm (ESC/POS, tear-off)",
        "description": "Small thermal printer without a cutter.",
        "values": {
            "receipt_printer_mode": "raw", "receipt_paper_width_mm": "57",
            "receipt_columns": "", "receipt_left_margin": "0",
            "receipt_feed_lines": "4", "receipt_form_feed": "1",
            "receipt_printer_escpos": "1", "receipt_printer_has_cutter": "0",
        },
    },
    {
        "id": "thermal_80_cutter",
        "name": "Thermal 80 mm with auto-cutter (ESC/POS)",
        "description": "The most common POS thermal printer. The printer feeds and cuts by itself.",
        "values": {
            "receipt_printer_mode": "raw", "receipt_paper_width_mm": "80",
            "receipt_columns": "", "receipt_left_margin": "0",
            "receipt_feed_lines": "2", "receipt_form_feed": "1",
            "receipt_printer_escpos": "1", "receipt_printer_has_cutter": "1",
        },
    },
    {
        "id": "thermal_80_teaoff",
        "name": "Thermal 80 mm, tear-off (no cutter)",
        "description": "80 mm thermal printer you tear by hand.",
        "values": {
            "receipt_printer_mode": "raw", "receipt_paper_width_mm": "80",
            "receipt_columns": "", "receipt_left_margin": "0",
            "receipt_feed_lines": "5", "receipt_form_feed": "1",
            "receipt_printer_escpos": "1", "receipt_printer_has_cutter": "0",
        },
    },
    {
        "id": "windows_driver_80",
        "name": "Windows driver, 80 mm (graphics / raster mode)",
        "description": "For a printer with its own Windows driver that can print graphics. "
                       "Not for a Generic / Text Only queue.",
        "values": {
            "receipt_printer_mode": "raster", "receipt_paper_width_mm": "80",
            "receipt_columns": "", "receipt_left_margin": "0",
            "receipt_feed_lines": "2", "receipt_form_feed": "1",
            "receipt_printer_escpos": "0", "receipt_printer_has_cutter": "0",
        },
    },
]


def get_profile(profile_id: str) -> dict | None:
    return next((p for p in PROFILES if p["id"] == profile_id), None)


def matching_profile(values: dict[str, str]) -> str | None:
    """The id of the profile whose values equal the current ones, if any."""
    from utils.receipt_layout import HARDWARE_DEFAULTS, validate_value
    for p in PROFILES:
        if all(validate_value(k, values.get(k, HARDWARE_DEFAULTS.get(k, "")))[1] == v
               for k, v in p["values"].items()):
            return p["id"]
    return None
