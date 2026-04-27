"""Usage counters поверх Redis для дневных и месячных лимитов."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.redis.client import get_redis

log = logging.getLogger(__name__)


class _RedisCounter(Protocol):
    async def incr(self, key: str) -> int: ...
    async def expire(self, key: str, time: int) -> object: ...


@dataclass(frozen=True, slots=True)
class UsageLimitDecision:
    allowed: bool
    reason: str | None = None


class UsageLimiter:
    """Проверяет soft usage limits. При сбоях Redis пропускает сообщение."""

    def __init__(
        self,
        *,
        settings: Settings | object | None = None,
        redis_client: _RedisCounter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._redis = redis_client if redis_client is not None else get_redis()

    async def check_and_increment(self, *, telegram_user_id: int) -> UsageLimitDecision:
        daily_limit = int(getattr(self._settings, "DAILY_USER_MESSAGE_LIMIT", 0) or 0)
        monthly_limit = int(
            getattr(self._settings, "MONTHLY_GLOBAL_MESSAGE_LIMIT", 0) or 0
        )
        if daily_limit <= 0 and monthly_limit <= 0:
            return UsageLimitDecision(allowed=True)

        if self._redis is None:
            log.warning("Usage limiter falling back to allow — Redis unavailable")
            return UsageLimitDecision(allowed=True)

        now = datetime.now(timezone.utc)
        checks: list[tuple[str, int, int]] = []
        if daily_limit > 0:
            checks.append(
                (
                    f"usage:user:{telegram_user_id}:daily:{now:%Y%m%d}",
                    daily_limit,
                    60 * 60 * 27,
                )
            )
        if monthly_limit > 0:
            checks.append(
                (
                    f"usage:global:monthly:{now:%Y%m}",
                    monthly_limit,
                    60 * 60 * 24 * 33,
                )
            )

        try:
            for key, limit, ttl in checks:
                count = await self._redis.incr(key)
                if count == 1:
                    await self._redis.expire(key, ttl)
                if count > limit:
                    return UsageLimitDecision(allowed=False, reason=key)
        except RedisError as exc:
            log.warning(
                "Usage limiter Redis error: %s — allowing request",
                exc.__class__.__name__,
            )
            return UsageLimitDecision(allowed=True)

        return UsageLimitDecision(allowed=True)


__all__ = ["UsageLimitDecision", "UsageLimiter"]
