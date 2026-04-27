"""Тесты толерантного резолвера DSN в app.config.

Проверяем:
- приоритет источников Postgres (DATABASE_URL > POSTGRES_URL > DATABASE_PRIVATE_URL >
  DATABASE_PUBLIC_URL > PG* > POSTGRES_*),
- приоритет источников Redis (REDIS_URL > REDIS_PRIVATE_URL > REDIS_PUBLIC_URL > REDIS*),
- нормализацию `postgresql://` → `postgresql+asyncpg://` для SQLAlchemy и обратно,
- маскирование пароля для безопасной печати,
- что `connection_sources` возвращает строковую метку источника.
"""

from __future__ import annotations

import os
from typing import Iterable

import pytest

from app.config import (
    Settings,
    mask_url_password,
    normalize_to_asyncpg,
    normalize_to_native,
)


# Все известные env-переменные, влияющие на резолвер. На время теста чистим их,
# чтобы pydantic-settings не подсасывал значения из реального окружения / .env.
_PG_ENVS: tuple[str, ...] = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "DATABASE_PRIVATE_URL",
    "DATABASE_PUBLIC_URL",
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGDATABASE",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)
_REDIS_ENVS: tuple[str, ...] = (
    "REDIS_URL",
    "REDIS_PRIVATE_URL",
    "REDIS_PUBLIC_URL",
    "REDISHOST",
    "REDISPORT",
    "REDISUSER",
    "REDISPASSWORD",
)
_OTHER_ENVS: tuple[str, ...] = ("APP_ENV", "ENV_FILE")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Чистим env и подменяем .env-файл на пустой, чтобы pydantic-settings не читал реальный."""
    for name in _PG_ENVS + _REDIS_ENVS + _OTHER_ENVS:
        monkeypatch.delenv(name, raising=False)
    # Подкладываем пустой .env, чтобы default-значения Settings не перетирались.
    empty_env = tmp_path / ".env.empty"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty_env))


def _set(monkeypatch: pytest.MonkeyPatch, items: Iterable[tuple[str, str]]) -> None:
    for name, value in items:
        monkeypatch.setenv(name, value)


def _make_settings() -> Settings:
    """Создаёт Settings без LRU-кеша get_settings() — каждый тест видит свежее окружение."""
    env_file = os.environ.get("ENV_FILE")
    if env_file:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return Settings()


# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------


def test_pg_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("DATABASE_URL", "postgresql://u:p@db.example:5432/app"),
            # Эти значения должны быть проигнорированы благодаря приоритету.
            ("PGHOST", "ignored"),
            ("PGUSER", "ignored"),
            ("PGDATABASE", "ignored"),
        ],
    )
    s = _make_settings()
    assert s.postgres_connection_source == "DATABASE_URL"
    assert s.database_url_native == "postgresql://u:p@db.example:5432/app"
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@db.example:5432/app"


def test_pg_postgres_url_used_when_database_url_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, [("POSTGRES_URL", "postgresql://u:p@db.example:5432/app")])
    s = _make_settings()
    assert s.postgres_connection_source == "POSTGRES_URL"
    assert s.sqlalchemy_url.startswith("postgresql+asyncpg://")


def test_pg_private_url_used_when_higher_priority_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(
        monkeypatch,
        [("DATABASE_PRIVATE_URL", "postgresql://u:p@db.private:5432/app")],
    )
    s = _make_settings()
    assert s.postgres_connection_source == "DATABASE_PRIVATE_URL"
    assert "db.private" in s.sqlalchemy_url


def test_pg_public_url_used_when_only_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("DATABASE_PUBLIC_URL", "postgresql://u:p@db.public:5432/app")])
    s = _make_settings()
    assert s.postgres_connection_source == "DATABASE_PUBLIC_URL"


def test_pg_built_from_pg_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("PGHOST", "postgres.railway.internal"),
            ("PGPORT", "5432"),
            ("PGUSER", "railway"),
            ("PGPASSWORD", "secret pass"),
            ("PGDATABASE", "railway"),
        ],
    )
    s = _make_settings()
    assert s.postgres_connection_source == "PGHOST+PGPORT+PGUSER+PGPASSWORD+PGDATABASE"
    # quote_plus кодирует пробел как '+', что валидно для userinfo-секции и
    # корректно декодируется asyncpg-ом.
    assert s.database_url_native == (
        "postgresql://railway:secret+pass@postgres.railway.internal:5432/railway"
    )
    assert s.sqlalchemy_url.startswith("postgresql+asyncpg://railway:")
    assert "secret pass" not in s.sqlalchemy_url


def test_pg_built_from_postgres_vars_compose_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(
        monkeypatch,
        [
            ("POSTGRES_HOST", "postgres"),
            ("POSTGRES_PORT", "5432"),
            ("POSTGRES_USER", "telegram_ai_core"),
            ("POSTGRES_PASSWORD", "telegram_ai_core_password"),
            ("POSTGRES_DB", "telegram_ai_core"),
        ],
    )
    s = _make_settings()
    assert (
        s.postgres_connection_source
        == "POSTGRES_HOST+POSTGRES_PORT+POSTGRES_USER+POSTGRES_PASSWORD+POSTGRES_DB"
    )
    assert "postgres:5432/telegram_ai_core" in s.database_url_native
    assert s.sqlalchemy_url.startswith("postgresql+asyncpg://")


def test_pg_database_url_beats_pghost(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("DATABASE_URL", "postgresql://u:p@db.example:5432/app"),
            ("PGHOST", "should-not-be-used"),
            ("PGUSER", "x"),
            ("PGPASSWORD", "x"),
            ("PGDATABASE", "x"),
        ],
    )
    s = _make_settings()
    assert s.postgres_connection_source == "DATABASE_URL"
    assert "db.example" in s.sqlalchemy_url
    assert "should-not-be-used" not in s.sqlalchemy_url


def test_pg_normalizes_to_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("DATABASE_URL", "postgresql://u:p@h:5432/d")])
    s = _make_settings()
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.database_url_native == "postgresql://u:p@h:5432/d"


def test_pg_handles_postgres_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("DATABASE_URL", "postgres://u:p@h:5432/d")])
    s = _make_settings()
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.database_url_native == "postgresql://u:p@h:5432/d"


def test_pg_already_asyncpg_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("DATABASE_URL", "postgresql+asyncpg://u:p@h/d")])
    s = _make_settings()
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@h/d"
    assert s.database_url_native == "postgresql://u:p@h/d"


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def test_redis_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("REDIS_URL", "redis://r.example:6379/0"),
            ("REDISHOST", "should-not-be-used"),
        ],
    )
    s = _make_settings()
    assert s.redis_connection_source == "REDIS_URL"
    assert s.effective_redis_url == "redis://r.example:6379/0"


def test_redis_private_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("REDIS_PRIVATE_URL", "redis://r.private:6379/0")])
    s = _make_settings()
    assert s.redis_connection_source == "REDIS_PRIVATE_URL"


def test_redis_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("REDIS_PUBLIC_URL", "redis://r.public:6379/0")])
    s = _make_settings()
    assert s.redis_connection_source == "REDIS_PUBLIC_URL"


def test_redis_built_from_redishost(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("REDISHOST", "redis.railway.internal"),
            ("REDISPORT", "6379"),
            ("REDISUSER", "default"),
            ("REDISPASSWORD", "secret"),
        ],
    )
    s = _make_settings()
    assert (
        s.redis_connection_source
        == "REDISHOST+REDISPORT+REDISUSER+REDISPASSWORD"
    )
    assert s.effective_redis_url == "redis://default:secret@redis.railway.internal:6379/0"


def test_redis_built_from_redishost_no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("REDISHOST", "redis.local")])
    s = _make_settings()
    assert s.redis_connection_source == "REDISHOST+REDISPORT+REDISUSER+REDISPASSWORD"
    assert s.effective_redis_url == "redis://redis.local:6379/0"


def test_redis_no_sources_returns_empty() -> None:
    s = _make_settings()
    assert s.redis_connection_source == "none"
    assert s.effective_redis_url == ""


# ---------------------------------------------------------------------------
# Connection sources dict
# ---------------------------------------------------------------------------


def test_connection_sources_combined(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("DATABASE_URL", "postgresql://u:p@h:5432/d"),
            ("REDIS_URL", "redis://h:6379/0"),
        ],
    )
    s = _make_settings()
    assert s.connection_sources == {
        "postgres": "DATABASE_URL",
        "redis": "REDIS_URL",
    }


# ---------------------------------------------------------------------------
# Mask password
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected_substring,forbidden_substring",
    [
        (
            "postgresql://user:supersecret@host:5432/db",
            "user:***@host:5432/db",
            "supersecret",
        ),
        (
            "redis://default:topsecret@redis.example:6379/0",
            "default:***@redis.example:6379/0",
            "topsecret",
        ),
        # URL без пароля — не должно сломаться.
        ("postgresql://just-host:5432/db", "just-host", "***"),
    ],
)
def test_mask_url_password(
    url: str, expected_substring: str, forbidden_substring: str
) -> None:
    masked = mask_url_password(url)
    assert expected_substring in masked
    assert forbidden_substring not in masked


def test_mask_url_password_empty() -> None:
    assert mask_url_password("") == ""


# ---------------------------------------------------------------------------
# Helpers normalize_to_asyncpg / normalize_to_native
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "incoming,expected",
    [
        ("postgresql://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgres://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        (
            "postgresql+asyncpg://u:p@h:5432/d",
            "postgresql+asyncpg://u:p@h:5432/d",
        ),
        ("", ""),
    ],
)
def test_normalize_to_asyncpg(incoming: str, expected: str) -> None:
    assert normalize_to_asyncpg(incoming) == expected


@pytest.mark.parametrize(
    "incoming,expected",
    [
        ("postgresql+asyncpg://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
        ("postgresql://u:p@h:5432/d", "postgresql://u:p@h:5432/d"),
        ("", ""),
    ],
)
def test_normalize_to_native(incoming: str, expected: str) -> None:
    assert normalize_to_native(incoming) == expected
