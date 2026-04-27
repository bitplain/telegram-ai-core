"""Тесты Redis-backed usage limits."""

from __future__ import annotations

from app.core.usage_limits import UsageLimitDecision, UsageLimiter


class _FakeSettings:
    DAILY_USER_MESSAGE_LIMIT = 0
    MONTHLY_GLOBAL_MESSAGE_LIMIT = 0


async def test_usage_limits_disabled_allow_without_redis() -> None:
    limiter = UsageLimiter(settings=_FakeSettings(), redis_client=None)

    decision = await limiter.check_and_increment(telegram_user_id=123)

    assert decision == UsageLimitDecision(allowed=True, reason=None)

