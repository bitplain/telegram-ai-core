"""Текст ежедневного digest для пользователя."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from app.core.news.providers.aggregate import aggregate_crypto_news
from app.core.price.eth import fetch_eth_usd_price
from app.utils.formatting import format_decimal


def digest_already_sent_for_utc_day(
    *, last_sent_at: datetime | None, utc_day: date
) -> bool:
    """True, если digest уже отправлялся в указанный UTC-календарный день."""
    if last_sent_at is None:
        return False
    return last_sent_at.astimezone(timezone.utc).date() == utc_day


async def build_daily_digest_text(
    *,
    eth_balance: Decimal,
    httpx_client: httpx.AsyncClient | None = None,
    llm_summary: str | None = None,
) -> str:
    """Формирует тело digest; при отсутствии LLM — только факты и fallback."""
    price = await fetch_eth_usd_price(client=httpx_client)
    news = await aggregate_crypto_news(client=httpx_client)

    parts: list[str] = ["<b>Daily digest</b> (UTC)", ""]
    parts.append(
        f"Ваш ручной баланс ETH (учёт в боте, не кошелёк): "
        f"<b>{format_decimal(eth_balance)}</b> ETH"
    )
    if price is not None:
        usd_val = eth_balance * price
        parts.append(
            f"ETH ~ <b>{format_decimal(price)}</b> USD (CoinGecko). "
            f"Оценка стоимости позиции: ~<b>{format_decimal(usd_val)}</b> USD."
        )
    else:
        parts.append("Цена ETH сейчас недоступна (CoinGecko).")

    parts.append("")
    parts.append("<b>Заголовки</b>:")
    for n in news[:10]:
        parts.append(f"• {n.title}")
        if (n.url or "").strip():
            parts.append(f"  <code>{n.url}</code>")

    if llm_summary and llm_summary.strip():
        parts.append("")
        parts.append("<b>Кратко (LLM)</b>:")
        parts.append(llm_summary.strip())

    return "\n".join(parts)


__all__ = ["build_daily_digest_text", "digest_already_sent_for_utc_day"]
