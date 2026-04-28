"""Форматирование чисел для пользовательских сообщений."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def format_decimal(value: Decimal, *, max_places: int = 8) -> str:
    """Форматирует Decimal без научной нотации, убирая лишние нули."""
    q = Decimal("1").scaleb(-max_places)  # 10^-max_places
    rounded = value.quantize(q, rounding=ROUND_HALF_UP)
    s = format(rounded, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def format_percent(value: Decimal, *, places: int = 2) -> str:
    """Проценты для отображения (значение уже в долях, например 0.05 → 5%)."""
    pct = (value * Decimal(100)).quantize(
        Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP
    )
    return f"{format_decimal(pct, max_places=places)}%"


__all__ = ["format_decimal", "format_percent"]
