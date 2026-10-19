"""
Test sheets for the calibration wizard. A raw/parallel-to-USB printer cannot
report anything back, so the program prints a sheet and asks the person two
simple questions instead of trusting what Windows says.

  1. Width test  — a column ruler. "What is the last column you can read on the
                   first ruler line?"  -> columns.
  2. Feed test   — numbered lines. "After tearing the paper off, what is the
                   last full LINE number on the torn-off piece?" -> feed lines.
"""
from __future__ import annotations

Line = tuple[str, str]

RULER_COLUMNS = 64          # longer than any receipt printer line, so it wraps
FEED_TEST_LINES = 16


def ruler_lines(max_cols: int = RULER_COLUMNS) -> list[Line]:
    tens = "".join(str((i // 10) % 10) if i % 10 == 0 else " " for i in range(1, max_cols + 1))
    ones = "".join(str(i % 10) for i in range(1, max_cols + 1))
    return [
        ("WIDTH TEST", "title"),
        ("Read the last number you can", "normal"),
        ("see on the FIRST ruler line.", "normal"),
        (tens, "normal"),
        (ones, "normal"),
        (tens, "normal"),
        (ones, "normal"),
    ]


def feed_test_lines(n: int = FEED_TEST_LINES) -> list[Line]:
    lines: list[Line] = [
        ("FEED TEST", "title"),
        ("When printing stops, tear the", "normal"),
        ("paper off. Find the last full", "normal"),
        ("numbered line on the torn-off", "normal"),
        ("piece (01 to %02d)." % n, "normal"),
        ("-" * 28, "div"),
    ]
    lines += [(f"LINE {i:02d} " + "." * 15, "normal") for i in range(1, n + 1)]
    return lines


def style_test_lines() -> list[Line]:
    return [
        ("STYLE TEST", "title"),
        ("MY STORE", "biz_name"),
        ("normal text  $1,234.56", "normal"),
        ("TOTAL:        $1,234.56", "total"),
        ("symbols: - x ' \" ... <= e n", "normal"),
        ("From: \u2014 \u00d7 \u2019 \u2026 \u2264 \u00e9 \u00f1", "normal"),
        ("(line above: raw characters)", "normal"),
    ]


def suggest_feed(total_lines: int, last_visible_line: int, margin: int = 1) -> int:
    """Blank lines needed so the last printed line clears the tear bar.
    Lines after `last_visible_line` were still inside the printer."""
    last = max(0, min(int(last_visible_line), total_lines))
    return (total_lines - last) + max(0, margin)
