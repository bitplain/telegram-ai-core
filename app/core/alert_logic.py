"""Парсинг и валидация цен для ETH alerts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Верхняя граница «разумного» ввода (защита от переполнения / мусора).
MAX_ETH_USD_ALERT = Decimal("10_000_000")


def parse_positive_usd_price(raw: str | None) -> tuple[Decimal | None, str | None]:
    """Возвращает (value, error_message_ru)."""
    s = (raw or "").strip()
    if not s:
        return None, "Укажи целевую цену в USD, например: /alert_eth 3500"
    try:
        value = Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None, "Некорректное число. Пример: /alert_eth 3500"
    if value <= 0:
        return None, "Цена должна быть положительной."
    if value > MAX_ETH_USD_ALERT:
        return None, "Слишком большое значение."
    return value, None


def resolve_alert_direction(
    *, target: Decimal, current: Decimal
) -> tuple[str | None, str | None]:
    """Возвращает ('above'|'below', error_ru)."""
    if target == current:
        return None, "Целевая цена совпадает с текущей — смысла в алерте нет."
    if target > current:
        return "above", None
    return "below", None


__all__ = ["parse_positive_usd_price", "resolve_alert_direction", "MAX_ETH_USD_ALERT"]
