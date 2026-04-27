"""Разбор аргументов /portfolio_add_eth."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_NUM_RE = re.compile(r"^\d+(\.\d+)?$")


@dataclass(frozen=True, slots=True)
class AddEthArgs:
    amount: Decimal
    price_usd_per_eth: float | None


def parse_add_eth_args(args: str) -> tuple[AddEthArgs | None, str | None]:
    """(результат, user-facing ошибка). ``None, None`` — пустой ввод."""
    parts = (args or "").strip().split()
    if not parts:
        return None, None
    if len(parts) > 2:
        return None, "Слишком много аргументов. Пример: 0.25 2000"
    if len(parts) == 1:
        raw_amt, raw_price = parts[0], None
    else:
        raw_amt, raw_price = parts[0], parts[1]

    if not _NUM_RE.match(raw_amt):
        return None, "Кол-во ETH — число, например 0.5"
    try:
        amount = Decimal(raw_amt)
    except (InvalidOperation, ValueError):
        return None, "Некорректное количество ETH. Пример: 0.5"
    if amount <= 0:
        return None, "Количество должно быть > 0"

    if not raw_price:
        return AddEthArgs(amount=amount, price_usd_per_eth=None), None

    if not _NUM_RE.match(raw_price):
        return None, "Цена в USD/ETH — число, например 2500"
    try:
        price = float(raw_price)
    except ValueError:
        return None, "Некорректная цена. Пример: 2500"
    if price <= 0:
        return None, "Цена должна быть > 0"

    return AddEthArgs(amount=amount, price_usd_per_eth=price), None


__all__ = ["AddEthArgs", "parse_add_eth_args"]
