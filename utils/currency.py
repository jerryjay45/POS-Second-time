"""
utils/currency.py
Shared currency formatting helper.

The business operates in Jamaica (JMD) where everyday prices commonly run
into the thousands (e.g. a box of cereal at $1,258.00) — not just the low
single/double-digit amounts typical of USD/CAD price tags. Every place that
formats a price MUST use format_currency() rather than an inline f-string
like f"${amount:.2f}", which prints "$1258.00" with no thousands separator
and is easy to misread, both on screen and on a printed receipt.
"""

from core.db_config import get as cfg_get


def format_currency(amount: float, symbol: str = None) -> str:
    """Format a number as currency with a thousands separator.

    format_currency(1258.5)      -> "$1,258.50"
    format_currency(1258.5, "J$") -> "J$1,258.50"
    format_currency(-42)         -> "-$42.00"

    symbol defaults to the configured currency_symbol setting when not
    given explicitly, so callers don't need to fetch it themselves.
    """
    if symbol is None:
        symbol = cfg_get("currency_symbol", "$")
    if amount < 0:
        return f"-{symbol}{-amount:,.2f}"
    return f"{symbol}{amount:,.2f}"


def format_number(value: float, decimals: int = 2) -> str:
    """Format a plain number (no currency symbol) with a thousands separator.
    Useful for quantities, percentages, or any large figure in a report."""
    return f"{value:,.{decimals}f}"
