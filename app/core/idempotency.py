"""Идемпотентность апдейтов Telegram.

Двухуровневая защита:
1) Быстрый Redis NX-cache (TTL ~ 24 часа) — для частых дублей.
2) Постоянная PG-таблица processed_updates с UNIQUE на telegram_update_id.

Возвращаем True, если апдейт ещё не обрабатывался.
"""

from __future__ import annotations

import logging

from redis.exceptions import RedisError

from app.db.repositories.processed_updates import ProcessedUpdateRepository
from app.db.session import session_scope
from app.redis.client import get_redis

log = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "tg:update:"
_REDIS_TTL_SECONDS = 24 * 3600


async def is_first_seen(update_id: int) -> bool:
    """Регистрирует update_id и возвращает True, если это первый просмотр.

    Шаги:
    - Если в Redis уже стоит ключ — это дубликат (False).
    - Иначе пытаемся сохранить в PG; PG — источник истины.
    - При успехе ставим Redis-ключ для быстрого ответа в следующий раз.
    """
    redis = get_redis()
    key = f"{_REDIS_KEY_PREFIX}{update_id}"

    if redis is not None:
        try:
            exists = await redis.exists(key)
            if exists:
                return False
        except RedisError:
            log.warning("Redis idempotency cache check failed — falling back to PG")

    async with session_scope() as session:
        repo = ProcessedUpdateRepository(session)
        inserted = await repo.try_register(update_id)

    if inserted and redis is not None:
        try:
            await redis.set(key, "1", ex=_REDIS_TTL_SECONDS, nx=True)
        except RedisError:
            log.warning("Failed to set Redis idempotency cache key for update %s", update_id)

    return inserted


__all__ = ["is_first_seen"]
