"""Тесты CoinGecko price provider и Redis-кеша."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.portfolio.price_provider import (
    EthMarketSnapshot,
    _fetch_from_coingecko,
    _write_cache,
    get_eth_market_snapshot,
)


@pytest.mark.asyncio
async def test_fetch_from_coingecko_parses_payload() -> None:
    payload = {
        "ethereum": {
            "usd": 2000.5,
            "rub": 180000.0,
            "usd_24h_change": -1.25,
        }
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        out = await _fetch_from_coingecko(client)
    assert out is not None
    assert out.price_usd == 2000.5
    assert out.price_rub == 180000.0
    assert out.change_24h_percent == -1.25


@pytest.mark.asyncio
async def test_write_cache_setex() -> None:
    fake = AsyncMock()
    fake.setex = AsyncMock()
    snap = EthMarketSnapshot(
        price_usd=100.0,
        price_rub=None,
        change_24h_percent=None,
    )
    with patch("app.core.portfolio.price_provider.get_redis", return_value=fake):
        await _write_cache(snap)
    fake.setex.assert_awaited_once()
    _key, ttl, _raw = fake.setex.call_args[0]
    assert ttl == 60


@pytest.mark.asyncio
async def test_get_eth_market_snapshot_http_error_user_facing() -> None:
    async def boom(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("no network")

    with patch("app.core.portfolio.price_provider.get_redis", return_value=None):
        with patch("httpx.AsyncClient") as ac:
            instance = AsyncMock()
            instance.__aenter__.return_value = instance
            instance.__aexit__.return_value = None
            instance.get = boom
            ac.return_value = instance
            snap, err = await get_eth_market_snapshot()
    assert snap is None
    assert err is not None
    assert "котировок" in err or "сервис" in err


@pytest.mark.asyncio
async def test_cache_hit_skips_network() -> None:
    cached = {
        "price_usd": 3000.0,
        "price_rub": 270000.0,
        "change_24h_percent": 0.1,
    }
    r = AsyncMock()
    r.get = AsyncMock(return_value=json.dumps(cached))

    with patch("app.core.portfolio.price_provider.get_redis", return_value=r):
        snap, err = await get_eth_market_snapshot()

    assert err is None
    assert snap is not None
    assert snap.price_usd == 3000.0
    r.get.assert_awaited()
