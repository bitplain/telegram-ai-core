"""Форматирование сумм для Telegram (кратко, с разделителями)."""

from __future__ import annotations

from decimal import Decimal


def format_eth(amount: Decimal) -> str:
    q = amount.quantize(Decimal("0.000001"))
    s = f"{q:f}".rstrip("0").rstrip(".")
    return s or "0"


def format_usd(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value:,.0f} USD".replace(",", " ")
    if abs(value) >= 100:
        return f"{value:,.2f} USD".replace(",", " ")
    return f"{value:.4f} USD".replace(",", " ")


def format_rub(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value:,.0f} RUB".replace(",", " ")
    if abs(value) >= 100:
        return f"{value:,.2f} RUB".replace(",", " ")
    return f"{value:.2f} RUB".replace(",", " ")


def format_percent(p: float) -> str:
    return f"{p:+.2f} %"
