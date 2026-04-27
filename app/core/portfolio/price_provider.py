"""Котировки ETH через публичный CoinGecko API + кеш Redis (60 с)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.redis.client import get_redis

log = logging.getLogger(__name__)

COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"
ETH_COIN_ID = "ethereum"
_CACHE_KEY = "price:eth:coingecko:v1"
_CACHE_TTL_SECONDS = 60
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 10.0
_MAX_RETRIES = 2


@dataclass(frozen=True, slots=True)
class EthMarketSnapshot:
    """Снимок рынка ETH (USD обязателен; RUB и 24h — если CoinGecko отдал)."""

    price_usd: float
    price_rub: float | None
    change_24h_percent: float | None


def _parse_coingecko_payload(data: Any) -> EthMarketSnapshot | None:
    if not isinstance(data, dict):
        return None
    eth = data.get(ETH_COIN_ID)
    if not isinstance(eth, dict):
        return None
    usd = eth.get("usd")
    if not isinstance(usd, (int, float)):
        return None
    rub = eth.get("rub")
    rub_f: float | None
    if isinstance(rub, (int, float)):
        rub_f = float(rub)
    else:
        rub_f = None
    ch = eth.get("usd_24h_change")
    ch_f: float | None
    if isinstance(ch, (int, float)):
        ch_f = float(ch)
    else:
        ch_f = None
    return EthMarketSnapshot(price_usd=float(usd), price_rub=rub_f, change_24h_percent=ch_f)


async def _read_cache() -> EthMarketSnapshot | None:
    client = get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(_CACHE_KEY)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    usd = obj.get("price_usd")
    if not isinstance(usd, (int, float)):
        return None
    rub = obj.get("price_rub")
    rub_f = float(rub) if isinstance(rub, (int, float)) else None
    ch = obj.get("change_24h_percent")
    ch_f = float(ch) if isinstance(ch, (int, float)) else None
    return EthMarketSnapshot(
        price_usd=float(usd),
        price_rub=rub_f,
        change_24h_percent=ch_f,
    )


async def _write_cache(snapshot: EthMarketSnapshot) -> None:
    client = get_redis()
    if client is None:
        return
    payload = json.dumps(
        {
            "price_usd": snapshot.price_usd,
            "price_rub": snapshot.price_rub,
            "change_24h_percent": snapshot.change_24h_percent,
        },
        ensure_ascii=False,
    )
    try:
        await client.setex(_CACHE_KEY, _CACHE_TTL_SECONDS, payload)
    except Exception:  # noqa: BLE001
        pass


async def _fetch_from_coingecko(client: httpx.AsyncClient) -> EthMarketSnapshot | None:
    params = {
        "ids": ETH_COIN_ID,
        "vs_currencies": "usd,rub",
        "include_24hr_change": "true",
    }
    r = await client.get(COINGECKO_SIMPLE_PRICE, params=params)
    r.raise_for_status()
    return _parse_coingecko_payload(r.json())


async def get_eth_market_snapshot() -> tuple[EthMarketSnapshot | None, str | None]:
    """Возвращает (снимок, сообщение_ошибки_для_пользователя).

    Сначала Redis-кеш; при промахе — CoinGecko с ретраями. Без падений наружу.
    """
    cached = await _read_cache()
    if cached is not None:
        return cached, None

    timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                snap = await _fetch_from_coingecko(client)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            last_exc = exc
            log.warning(
                "eth_price_fetch_failed",
                extra={"attempt": attempt, "error": exc.__class__.__name__},
            )
            continue
        if snap is None:
            last_exc = ValueError("unexpected_coingecko_shape")
            continue
        await _write_cache(snap)
        return snap, None

    if last_exc is not None:
        log.info("eth_price_unavailable: %s", last_exc.__class__.__name__)
    return None, (
        "Не удалось получить цену ETH: сервис котировок временно недоступен. "
        "Попробуй чуть позже."
    )


async def get_eth_price_usd() -> tuple[float | None, str | None]:
    """Текущая цена ETH в USD (с кешом)."""
    snap, err = await get_eth_market_snapshot()
    if snap is None:
        return None, err
    return snap.price_usd, None


async def get_eth_price_rub() -> tuple[float | None, str | None]:
    """Текущая цена ETH в RUB, если CoinGecko отдал курс; иначе (None, None) без ошибки."""
    snap, err = await get_eth_market_snapshot()
    if snap is None:
        return None, err
    return snap.price_rub, None if snap.price_rub is not None else "Курс ETH/RUB сейчас недоступен."


__all__ = [
    "EthMarketSnapshot",
    "get_eth_market_snapshot",
    "get_eth_price_usd",
    "get_eth_price_rub",
]
