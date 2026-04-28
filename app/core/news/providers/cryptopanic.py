"""Новости с CryptoPanic (опционально по API-ключу)."""

from __future__ import annotations

import logging
import httpx

from app.config import get_settings
from app.core.news.schemas import NewsItem

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def fetch_cryptopanic_news(
    *,
    client: httpx.AsyncClient | None = None,
    limit: int = 10,
) -> list[NewsItem]:
    api_key = (get_settings().CRYPTOPANIC_API_KEY or "").strip()
    if not api_key:
        return []

    own_client = client is None
    c = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        response = await c.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={"auth_token": api_key, "public": "true", "kind": "news"},
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        out: list[NewsItem] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            title = row.get("title")
            url = row.get("url") or row.get("source", {}).get("url")
            if not title or not url:
                continue
            out.append(NewsItem(title=str(title).strip(), url=str(url).strip()))
            if len(out) >= limit:
                break
        return out
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        log.debug("CryptoPanic fetch failed", exc_info=False)
        return []
    finally:
        if own_client:
            await c.aclose()


__all__ = ["NewsItem", "fetch_cryptopanic_news"]
