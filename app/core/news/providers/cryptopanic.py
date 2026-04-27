"""CryptoPanic API (опциональный auth token)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.news.schemas import NewsItem

log = logging.getLogger(__name__)

CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1/posts/"


async def fetch_cryptopanic_news(
    *,
    client: httpx.AsyncClient,
    auth_token: str | None,
    limit: int,
) -> list[NewsItem]:
    """Загружает посты по ETH; без токена запрос может вернуть 401 — тогда []."""
    params: dict[str, Any] = {"currencies": "ETH", "public": "true"}
    if auth_token:
        params["auth_token"] = auth_token
    try:
        resp = await client.get(CRYPTOPANIC_BASE, params=params, timeout=15.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        log.debug("CryptoPanic request failed", exc_info=True)
        return []

    try:
        data = resp.json()
    except ValueError:
        return []

    results = data.get("results")
    if not isinstance(results, list):
        return []

    out: list[NewsItem] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url:
            continue
        source_obj = row.get("source")
        source = "CryptoPanic"
        if isinstance(source_obj, dict):
            source = str(source_obj.get("title") or source_obj.get("domain") or source).strip() or "CryptoPanic"
        out.append(NewsItem(title=title[:500], source=source[:120], url=url[:2048]))
        if len(out) >= limit:
            break
    return out
