"""Агрегация новостей: CryptoPanic → RSS; без выдумывания."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.core.news.providers.cryptopanic import fetch_cryptopanic_news
from app.core.news.providers.rss import fetch_rss_crypto_news
from app.core.news.schemas import NewsItem

log = logging.getLogger(__name__)

NEWS_UNAVAILABLE = "Источники временно недоступны"


async def fetch_crypto_news(
    *,
    client: httpx.AsyncClient | None = None,
    min_items: int = 3,
    max_items: int = 5,
) -> tuple[list[NewsItem], str | None]:
    """Возвращает ``(items, None)`` или ``([], NEWS_UNAVAILABLE)``.

    ``min_items`` — если меньше реальных записей после всех источников,
    считаем сбой и отдаём пусто с сообщением для пользователя.
    """
    limit = max(min_items, min(max_items, 5))
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": "TelegramAICore/1.0"})

    items: list[NewsItem] = []
    try:
        settings = get_settings()
        token = (settings.CRYPTOPANIC_API_KEY or "").strip() or None
        items = await fetch_cryptopanic_news(
            client=client, auth_token=token, limit=limit
        )
        if len(items) < min_items:
            rss_items = await fetch_rss_crypto_news(client=client, limit=limit)
            seen = {x.url for x in items}
            for it in rss_items:
                if it.url in seen:
                    continue
                items.append(it)
                seen.add(it.url)
                if len(items) >= limit:
                    break
    except Exception:  # noqa: BLE001
        log.exception("fetch_crypto_news failed")
        items = []
    finally:
        if own_client:
            await client.aclose()

    if len(items) < min_items:
        return [], NEWS_UNAVAILABLE
    return items[:limit], None
