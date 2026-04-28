"""RSS-провайдеры новостей (title + link только)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from app.core.news.schemas import NewsItem

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(12.0, connect=5.0)


RSS_FEEDS: tuple[tuple[str, str], ...] = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


async def fetch_rss_feed(
    feed_url: str,
    *,
    client: httpx.AsyncClient,
    per_feed_limit: int = 8,
) -> list[NewsItem]:
    try:
        response = await client.get(feed_url)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:  # noqa: BLE001
        log.debug("RSS parse failed for feed", exc_info=False)
        return []

    channel = root
    if _local_name(root.tag).lower() == "rss":
        channel = root.find("{*}channel") or root.find("channel")
    if channel is None:
        return []

    out: list[NewsItem] = []
    seen_item_ids: set[int] = set()
    for item in channel.findall(".//item") + channel.findall(".//{*}item"):
        if id(item) in seen_item_ids:
            continue
        seen_item_ids.add(id(item))
        title_el = item.find("title") or item.find("{*}title")
        link_el = item.find("link") or item.find("{*}link")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        if not title or not link:
            continue
        out.append(NewsItem(title=title, url=link))
        if len(out) >= per_feed_limit:
            break
    return out


async def fetch_all_rss_news(
    *,
    client: httpx.AsyncClient | None = None,
    per_feed_limit: int = 8,
) -> list[NewsItem]:
    own_client = client is None
    c = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    merged: list[NewsItem] = []
    try:
        for _name, url in RSS_FEEDS:
            try:
                merged.extend(
                    await fetch_rss_feed(url, client=c, per_feed_limit=per_feed_limit)
                )
            except Exception:  # noqa: BLE001
                log.debug("RSS feed iteration failed", exc_info=False)
        return merged
    finally:
        if own_client:
            await c.aclose()


__all__ = ["NewsItem", "RSS_FEEDS", "fetch_rss_feed", "fetch_all_rss_news"]
