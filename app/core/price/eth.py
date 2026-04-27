"""Текущая цена ETH (CoinGecko публичный API)."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


async def fetch_eth_usd_price(*, client: httpx.AsyncClient | None = None) -> float | None:
    """Возвращает цену ETH в USD или None при ошибке."""
    settings = get_settings()
    url = f"{settings.COINGECKO_BASE_URL.rstrip('/')}/simple/price"
    params = {"ids": "ethereum", "vs_currencies": "usd"}
    own = client is None
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": "TelegramAICore/1.0"})
    try:
        resp = await client.get(url, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        eth = data.get("ethereum")
        if not isinstance(eth, dict):
            return None
        price = eth.get("usd")
        if isinstance(price, (int, float)):
            return float(price)
        return None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        log.debug("ETH price fetch failed", exc_info=True)
        return None
    finally:
        if own:
            await client.aclose()
