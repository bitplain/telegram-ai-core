"""Текст ежедневного дайджеста (MVP, без LLM)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal


def format_daily_digest_text(
    *,
    digest_date: date,
    eth_price_usd: Decimal,
) -> str:
    """Короткий HTML-дайджест для Telegram."""
    d = digest_date.isoformat()
    price = f"{eth_price_usd:.2f}"
    return (
        f"<b>Daily digest</b> ({d} UTC)\n\n"
        f"ETH ≈ <b>${price}</b> USD\n\n"
        "<i>MVP: один индикатор. Полный portfolio digest — позже.</i>"
    )


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


__all__ = ["format_daily_digest_text", "utc_today"]
