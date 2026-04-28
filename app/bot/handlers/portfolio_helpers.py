"""Парсинг аргументов /add_eth (Decimal, без float)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Максимум для защиты от переполнения и явного мусора.
MAX_ADD_ETH = Decimal("1_000_000")


def parse_add_eth_amount(raw: str | None) -> tuple[Decimal | None, str | None]:
    """Возвращает (amount, error_ru). Только строго положительные значения."""
    s = (raw or "").strip()
    if not s:
        return None, "Укажи количество ETH, например: /add_eth 0.5"
    try:
        value = Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None, "Некорректное число. Пример: /add_eth 0.25"
    if value <= 0:
        return None, "Количество должно быть больше нуля."
    if value > MAX_ADD_ETH:
        return None, "Слишком большое значение."
    return value, None


__all__ = ["parse_add_eth_amount", "MAX_ADD_ETH"]
