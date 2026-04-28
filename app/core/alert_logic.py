"""Логика срабатывания ETH price alerts."""

from __future__ import annotations

from decimal import Decimal


def is_price_triggered(
    *,
    current_price_usd: Decimal,
    target_price_usd: Decimal,
    direction: str,
) -> bool:
    """True если текущая цена пересекла цель в нужную сторону."""
    if direction == "above":
        return current_price_usd >= target_price_usd
    if direction == "below":
        return current_price_usd <= target_price_usd
    return False


__all__ = ["is_price_triggered"]
