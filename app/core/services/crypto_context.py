"""Контекст для крипто-аналитика: портфель, цена ETH, заголовки новостей."""

from __future__ import annotations

import logging

import httpx

from app.core.news.providers.aggregate import NEWS_UNAVAILABLE, fetch_crypto_news
from app.core.price.eth import fetch_eth_usd_price
from app.db.repositories.users import UserRepository
from app.db.session import AsyncSession
from app.utils.formatting import format_decimal

log = logging.getLogger(__name__)


async def build_crypto_analyst_context_block(
    session: AsyncSession,
    *,
    telegram_user_id: int,
) -> str:
    """Текстовый блок для дополнения system prompt (только факты из API/БД)."""
    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(telegram_user_id)
    eth_amount = float(user.eth_balance or 0) if user else 0.0

    async with httpx.AsyncClient(headers={"User-Agent": "TelegramAICore/1.0"}) as client:
        price = await fetch_eth_usd_price(client=client)
        news_items, err = await fetch_crypto_news(client=client, min_items=3, max_items=5)

    lines: list[str] = []
    lines.append(f"Портфель пользователя (ETH на учёте в боте): {format_decimal(eth_amount)} ETH")
    if price is not None:
        lines.append(f"Текущая ориентировочная цена ETH (USD, внешний API): ${format_decimal(price, max_decimals=2)}")
    else:
        lines.append("Текущая цена ETH сейчас недоступна из внешнего API.")

    if err:
        lines.append(f"Новости: {err}")
    elif news_items:
        lines.append("Последние заголовки (реальные источники; не выдумывать дополнительные):")
        for i, it in enumerate(news_items, start=1):
            lines.append(f"{i}. [{it.source}] {it.title}\n   URL: {it.url}")
    else:
        lines.append(NEWS_UNAVAILABLE)

    return "\n".join(lines)
