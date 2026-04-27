"""Диагностика конфигурации перед стартом приложения на Railway.

Подгружает Settings, печатает безопасные сводки (host, источник, без паролей)
и валит exit-код 1, если Postgres / Redis не сконфигурированы под Railway.

Считается, что Compose-стиль `POSTGRES_*` — это локальный фолбэк для
docker-compose; на Railway он не должен использоваться как единственный
источник, поэтому на railway/production мы требуем явные Railway-переменные.

Никогда не печатает raw DATABASE_URL / REDIS_URL и пароли.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

# При запуске из Docker-контейнера PYTHONPATH=/app задан в Dockerfile,
# но при локальном запуске может быть пустым — добавляем cwd как safety net.
sys.path.insert(0, ".")

from app.config import (  # noqa: E402
    Settings,
    get_settings,
    mask_url_password,
)


def _safe_host(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host
    except Exception:  # noqa: BLE001
        return ""


def _safe_port(url: str, default: int | None = None) -> int | None:
    if not url:
        return default
    try:
        parsed = urlparse(url)
        return parsed.port or default
    except Exception:  # noqa: BLE001
        return default


def _safe_db(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = parsed.path or ""
        return path.lstrip("/") or ""
    except Exception:  # noqa: BLE001
        return ""


_PG_SOURCE_HINT = (
    "[bootstrap] No Postgres connection variables detected.\n"
    "Add to Railway app-service Variables:\n"
    "  DATABASE_URL=${{Postgres.DATABASE_URL}}\n"
    "or run: bash scripts/railway-bind.sh\n"
    "Supported alternatives: POSTGRES_URL, DATABASE_PRIVATE_URL, "
    "DATABASE_PUBLIC_URL, PGHOST+PGPORT+PGUSER+PGPASSWORD+PGDATABASE."
)

_REDIS_SOURCE_HINT = (
    "[bootstrap] No Redis connection variables detected.\n"
    "Add to Railway app-service Variables:\n"
    "  REDIS_URL=${{Redis.REDIS_URL}}\n"
    "or run: bash scripts/railway-bind.sh\n"
    "Supported alternatives: REDIS_PRIVATE_URL, REDIS_PUBLIC_URL, "
    "REDISHOST+REDISPORT+REDISUSER+REDISPASSWORD."
)


_RAILWAY_PG_VARS: tuple[str, ...] = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "DATABASE_PRIVATE_URL",
    "DATABASE_PUBLIC_URL",
    "PGHOST",
)
_RAILWAY_REDIS_VARS: tuple[str, ...] = (
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
    "REDISHOST",
)


def _has_any_explicit_var(names: tuple[str, ...]) -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in names)


def _print_summary(settings: Settings) -> tuple[bool, bool]:
    """Печатает безопасную сводку и возвращает (pg_ok, redis_ok).

    На strict-окружениях (railway/production) валидным считается только
    наличие явных Railway-переменных — Compose-фолбэк POSTGRES_* не
    спасает.
    """
    strict = settings.is_strict_env

    print(
        f"[bootstrap] APP_ENV={settings.APP_ENV} "
        f"TELEGRAM_MODE={settings.TELEGRAM_MODE} "
        f"OPENROUTER_MODEL={settings.OPENROUTER_MODEL}",
        flush=True,
    )

    pg_url = settings.database_url_native
    pg_source = settings.postgres_connection_source
    explicit_pg = _has_any_explicit_var(_RAILWAY_PG_VARS)
    pg_ok = bool(pg_url) and (not strict or explicit_pg)
    if pg_ok:
        host = _safe_host(pg_url)
        db = _safe_db(pg_url)
        print(
            f"[bootstrap] Postgres: source={pg_source} host={host} db={db}",
            flush=True,
        )
    else:
        print(_PG_SOURCE_HINT, flush=True)

    redis_url = settings.effective_redis_url
    redis_source = settings.redis_connection_source
    explicit_redis = _has_any_explicit_var(_RAILWAY_REDIS_VARS)
    redis_ok = bool(redis_url) and (not strict or explicit_redis)
    if redis_ok:
        host = _safe_host(redis_url)
        port = _safe_port(redis_url, 6379)
        print(
            f"[bootstrap] Redis:    source={redis_source} host={host} port={port}",
            flush=True,
        )
    else:
        print(_REDIS_SOURCE_HINT, flush=True)

    print(
        "[bootstrap] TELEGRAM_BOT_TOKEN: "
        + ("set" if settings.TELEGRAM_BOT_TOKEN else "MISSING"),
        flush=True,
    )
    print(
        "[bootstrap] OPENROUTER_API_KEY: "
        + ("set" if settings.OPENROUTER_API_KEY else "MISSING"),
        flush=True,
    )

    _ = mask_url_password  # доступно для будущей отладки

    return pg_ok, redis_ok


def main() -> int:
    # Settings.model_validator падает, если в strict-env нет PG/Redis.
    # Для дружелюбной диагностики пробуем сначала с APP_ENV=local, потом
    # уже репортим реальное состояние и нужный source.
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001
        # Fallback: подгружаем без strict-валидации, чтобы сохранить
        # подробную распечатку источников.
        original_env = os.environ.get("APP_ENV", "")
        os.environ["APP_ENV"] = "local"
        try:
            from app.config import reload_settings  # noqa: WPS433

            settings = reload_settings()
        finally:
            if original_env:
                os.environ["APP_ENV"] = original_env
            else:
                os.environ.pop("APP_ENV", None)
        # Восстанавливаем strict-флаг через прямую правку поля,
        # чтобы _print_summary применил строгие правила.
        try:
            object.__setattr__(settings, "APP_ENV", original_env or "railway")
        except Exception:  # noqa: BLE001
            pass

    pg_ok, redis_ok = _print_summary(settings)

    if not pg_ok or not redis_ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
