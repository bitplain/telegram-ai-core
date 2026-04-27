"""Rate limiting через Redis.

Используем простой fixed-window: ключ rl:{user_id}:{window_index}
с TTL = window_seconds. INCR + EXPIRE на первой записи. Дешёво и достаточно
для MVP. Если Redis недоступен — пропускаем сообщение (allow) и пишем warning.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.config import get_settings
from app.redis.client import get_redis

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    reset_in_seconds: int


class RateLimiter:
    """Fixed-window лимитер на Redis с graceful-degradation."""

    def __init__(
        self,
        *,
        max_messages: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self._max_messages = max_messages or settings.RATE_LIMIT_MESSAGES
        self._window_seconds = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS

    async def check(self, user_id: int) -> RateLimitDecision:
        """Проверяет, можно ли пользователю отправить ещё одно сообщение."""
        redis = get_redis()
        now = int(time.time())
        window_start = now - (now % self._window_seconds)
        ttl = self._window_seconds - (now - window_start)
        key = f"rl:{user_id}:{window_start}"

        if redis is None:
            log.warning("Rate limiter falling back to allow — Redis unavailable")
            return RateLimitDecision(
                allowed=True, remaining=self._max_messages - 1, reset_in_seconds=ttl
            )

        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, ttl + 1)
        except RedisError as exc:
            log.warning("Rate limiter Redis error: %s — allowing request", exc.__class__.__name__)
            return RateLimitDecision(
                allowed=True, remaining=self._max_messages - 1, reset_in_seconds=ttl
            )

        remaining = max(0, self._max_messages - count)
        allowed = count <= self._max_messages
        return RateLimitDecision(
            allowed=allowed, remaining=remaining, reset_in_seconds=ttl
        )


__all__ = ["RateLimiter", "RateLimitDecision"]
