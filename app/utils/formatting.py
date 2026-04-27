"""Форматирование чисел для пользовательского интерфейса."""

from __future__ import annotations


def format_decimal(value: float, *, max_decimals: int = 8) -> str:
    """Форматирует число с разделителем тысяч; дробная часть без лишних нулей."""
    s = f"{value:,.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def format_percent(value: float, *, decimals: int = 1) -> str:
    """Процент с округлением."""
    rounded = round(value, decimals)
    fmt = f"{rounded:,.{decimals}f}"
    if "." in fmt:
        fmt = fmt.rstrip("0").rstrip(".")
    return f"{fmt}%"
