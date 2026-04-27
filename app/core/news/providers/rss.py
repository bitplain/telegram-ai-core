"""RSS-фиды крупных изданий (CoinDesk, The Block и др.)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from html import unescape

import httpx

from app.core.news.schemas import NewsItem

log = logging.getLogger(__name__)

# Публичные RSS; только заголовок/link из фида — без выдумывания текста.
RSS_FEEDS: tuple[tuple[str, str], ...] = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
)


def _strip_html(text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", text)
    return unescape(" ".join(t.split())).strip()


async def fetch_rss_feed(
    *,
    client: httpx.AsyncClient,
    source_name: str,
    feed_url: str,
    per_feed_limit: int,
) -> list[NewsItem]:
    try:
        resp = await client.get(feed_url, timeout=20.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        log.debug("RSS fetch failed for %s", source_name, exc_info=True)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        items = root.findall(".//item")
    else:
        items = channel.findall("item")

    out: list[NewsItem] = []
    for item in items:
        if len(out) >= per_feed_limit:
            break
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or link_el is None or title_el.text is None:
            continue
        title = _strip_html(title_el.text.strip())
        link = (link_el.text or "").strip()
        if not title or not link:
            continue
        out.append(NewsItem(title=title[:500], source=source_name, url=link[:2048]))
    return out


async def fetch_rss_crypto_news(
    *,
    client: httpx.AsyncClient,
    limit: int,
) -> list[NewsItem]:
    """Собирает новости из нескольких RSS до общего лимита."""
    collected: list[NewsItem] = []
    per = max(2, min(3, limit // len(RSS_FEEDS) + 1))
    for source_name, url in RSS_FEEDS:
        if len(collected) >= limit:
            break
        batch = await fetch_rss_feed(
            client=client,
            source_name=source_name,
            feed_url=url,
            per_feed_limit=per,
        )
        for it in batch:
            if len(collected) >= limit:
                break
            if any(x.url == it.url for x in collected):
                continue
            collected.append(it)
    return collected[:limit]
