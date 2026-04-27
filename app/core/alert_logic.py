"""Чистая логика срабатывания ценового алерта (для тестов и воркера)."""

from __future__ import annotations


def alert_should_fire(
    *, current_price_usd: float, target_price_usd: float, direction: str
) -> bool:
    if direction == "above":
        return current_price_usd >= target_price_usd
    if direction == "below":
        return current_price_usd <= target_price_usd
    return False
