"""Async Redis-клиент с graceful-degradation.

В тестах/локально Redis может быть недоступен — все вызовы должны
возвращать безопасное поведение (None / True / "пропускаем"), без падений.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.config import get_settings

log = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis | None:
    """Инициализирует Redis-пул. Возвращает None, если URL не задан или соединиться не удалось."""
    global _redis
    if _redis is not None:
        return _redis

    settings = get_settings()
    url = settings.REDIS_URL
    if not url:
        log.warning("REDIS_URL is empty — Redis features (rate limit, idempotency cache) disabled.")
        return None

    try:
        client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        await client.ping()
    except RedisError as exc:
        log.error("Failed to connect to Redis: %s", exc.__class__.__name__)
        return None
    except Exception:  # noqa: BLE001
        log.exception("Unexpected error while connecting to Redis")
        return None

    _redis = client
    log.info("Redis client initialized")
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:  # noqa: BLE001
            log.warning("Error while closing Redis client")
    _redis = None


def get_redis() -> aioredis.Redis | None:
    """Возвращает текущий Redis-клиент (или None при graceful-degradation)."""
    return _redis


async def ping() -> bool:
    """Проверка готовности Redis для /ready."""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(await client.ping())
    except RedisError:
        return False


__all__ = ["init_redis", "close_redis", "get_redis", "ping"]
