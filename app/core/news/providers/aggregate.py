"""Агрегация новостей из нескольких провайдеров."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.core.news.schemas import NewsItem
from app.core.news.providers.cryptopanic import fetch_cryptopanic_news
from app.core.news.providers.rss import fetch_all_rss_news

log = logging.getLogger(__name__)

MAX_ITEMS = 15

FALLBACK_MESSAGE = (
    "Новости сейчас недоступны (внешние источники не ответили или вернули пустой ответ)."
)


def _norm_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        parsed = urlparse(u)
        netloc = (parsed.netloc or "").lower()
        path = (parsed.path or "").rstrip("/").lower()
        return f"{netloc}{path}"
    except Exception:  # noqa: BLE001
        return u.lower()


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen_url: set[str] = set()
    seen_title: set[str] = set()
    out: list[NewsItem] = []
    for it in items:
        nu = _norm_url(it.url)
        tl = (it.title or "").strip().lower()
        if nu and nu in seen_url:
            continue
        if tl and tl in seen_title:
            continue
        if nu:
            seen_url.add(nu)
        if tl:
            seen_title.add(tl)
        out.append(it)
        if len(out) >= MAX_ITEMS:
            break
    return out


async def aggregate_crypto_news(
    *,
    client: httpx.AsyncClient | None = None,
) -> list[NewsItem]:
    """Собирает новости; при полной недоступности возвращает один fallback-элемент."""
    own = client is None
    c = client or httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0))
    try:
        rss_items = await fetch_all_rss_news(client=c)
        cp_items = await fetch_cryptopanic_news(client=c)
        merged = _dedupe([*cp_items, *rss_items])
        if not merged:
            log.info("news_aggregate_empty_using_fallback")
            return [NewsItem(title=FALLBACK_MESSAGE, url="")]
        return merged
    finally:
        if own:
            await c.aclose()


__all__ = ["aggregate_crypto_news", "MAX_ITEMS", "FALLBACK_MESSAGE"]
