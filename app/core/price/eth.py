"""Получение spot-цены ETH в USD через публичный API CoinGecko."""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

log = logging.getLogger(__name__)

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=ethereum&vs_currencies=usd"
)
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def fetch_eth_usd_price(
    client: httpx.AsyncClient | None = None,
) -> Decimal | None:
    """Возвращает цену ETH/USD или None при ошибке/некорректном ответе."""
    own_client = client is None
    c = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        response = await c.get(COINGECKO_URL)
        response.raise_for_status()
        data = response.json()
        raw = data.get("ethereum", {}).get("usd")
        if raw is None:
            return None
        return Decimal(str(raw))
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        log.debug("ETH price fetch failed or invalid response", exc_info=False)
        return None
    finally:
        if own_client:
            await c.aclose()


__all__ = ["fetch_eth_usd_price", "COINGECKO_URL"]
