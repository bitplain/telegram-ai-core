"""Скрипт ожидания готовности PostgreSQL и Redis перед стартом приложения.

Используется в entrypoint.sh для гарантии, что зависимые сервисы подняты.
В CI/Compose сервисы уже имеют healthcheck-и, но на голых машинах
этот скрипт даёт дополнительную страховку.
"""

from __future__ import annotations

import asyncio
import sys
import time
from urllib.parse import urlparse

import asyncpg
import redis.asyncio as aioredis

# Импортируем настройки уже после того, как PYTHONPATH настроен.
sys.path.insert(0, "/app")

from app.config import get_settings  # noqa: E402


MAX_WAIT_SECONDS = 60
RETRY_SLEEP_SECONDS = 2.0


async def _wait_postgres(database_url: str) -> bool:
    """Пытается установить соединение с PostgreSQL до тайм-аута."""
    # asyncpg не понимает driver-prefix postgresql+asyncpg://, конвертим обратно.
    if database_url.startswith("postgresql+asyncpg://"):
        normalized = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    else:
        normalized = database_url

    deadline = time.monotonic() + MAX_WAIT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncpg.connect(normalized, timeout=5)
            await conn.execute("SELECT 1")
            await conn.close()
            print("[wait-for-services] PostgreSQL is ready.", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(RETRY_SLEEP_SECONDS)
    print(
        f"[wait-for-services] PostgreSQL is NOT ready: {last_error!r}",
        file=sys.stderr,
        flush=True,
    )
    return False


async def _wait_redis(redis_url: str) -> bool:
    """Пытается выполнить PING на Redis до тайм-аута."""
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        client: aioredis.Redis | None = None
        try:
            client = aioredis.from_url(redis_url, socket_timeout=5)
            pong = await client.ping()
            if pong:
                print("[wait-for-services] Redis is ready.", flush=True)
                return True
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001, S110
                    pass
        await asyncio.sleep(RETRY_SLEEP_SECONDS)

    print(
        f"[wait-for-services] Redis is NOT ready: {last_error!r}",
        file=sys.stderr,
        flush=True,
    )
    return False


def _mask_url(url: str) -> str:
    """Маскируем пароль в URL перед печатью."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(parsed.password, "***")
            return parsed._replace(netloc=netloc).geturl()
    except Exception:  # noqa: BLE001
        pass
    return url


async def main() -> int:
    settings = get_settings()
    database_url = settings.effective_database_url
    redis_url = settings.REDIS_URL

    if not database_url:
        print("[wait-for-services] DATABASE_URL is empty — skipping PG check.", flush=True)
        pg_ok = True
    else:
        print(f"[wait-for-services] Waiting for PG at {_mask_url(database_url)}", flush=True)
        pg_ok = await _wait_postgres(database_url)

    if not redis_url:
        print("[wait-for-services] REDIS_URL is empty — skipping Redis check.", flush=True)
        redis_ok = True
    else:
        print(f"[wait-for-services] Waiting for Redis at {_mask_url(redis_url)}", flush=True)
        redis_ok = await _wait_redis(redis_url)

    return 0 if (pg_ok and redis_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
