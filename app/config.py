"""Application configuration via pydantic-settings v2.

Все настройки приходят из переменных окружения / .env-файла.
Никакие секреты в коде не хранятся и не логируются.

Резолвер DSN толерантен к разным форматам: поддерживает Railway (DATABASE_URL,
PGHOST+PGPORT+..., REDIS_URL, REDISHOST+REDISPORT+...), Compose (POSTGRES_*),
а также public/private-варианты Railway (DATABASE_PRIVATE_URL,
DATABASE_PUBLIC_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus, urlparse, urlunparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Поднимается, если конфигурация некорректна для прод-окружений."""


AppEnv = Literal["local", "railway", "production"]
TelegramMode = Literal["polling", "webhook"]
BotAccessMode = Literal["public", "allowlist", "admin_only"]


# Префикс asyncpg-драйвера для SQLAlchemy.
_ASYNC_DRIVER_PREFIX = "postgresql+asyncpg://"
_NATIVE_PG_PREFIXES = ("postgresql://", "postgres://")


def mask_url_password(url: str) -> str:
    """Маскирует пароль в DSN перед безопасной печатью.

    Возвращает исходную строку, если распарсить не удалось — но без пароля.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return "<unparseable>"
    if not parsed.password:
        return url
    user = parsed.username or ""
    host = parsed.hostname or ""
    netloc = ""
    if user:
        netloc += user
        netloc += ":***"
        netloc += "@"
    netloc += host
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def normalize_to_asyncpg(url: str) -> str:
    """Возвращает DSN с явным драйвером asyncpg для async SQLAlchemy."""
    if not url:
        return ""
    if url.startswith(_ASYNC_DRIVER_PREFIX):
        return url
    if url.startswith("postgres://"):
        return _ASYNC_DRIVER_PREFIX + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return _ASYNC_DRIVER_PREFIX + url[len("postgresql://") :]
    return url


def normalize_to_native(url: str) -> str:
    """Возвращает каноничный native DSN c префиксом postgresql://.

    Приводит `postgresql+asyncpg://` и `postgres://` к `postgresql://`.
    """
    if not url:
        return ""
    if url.startswith(_ASYNC_DRIVER_PREFIX):
        return "postgresql://" + url[len(_ASYNC_DRIVER_PREFIX) :]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


class Settings(BaseSettings):
    """Все настройки приложения. Имя совпадает с env-переменной."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: AppEnv = "local"
    LOG_LEVEL: str = "INFO"

    SERVER_HOST: str = "0.0.0.0"
    # SERVER_PORT — fallback. Финальный порт берётся через .effective_port.
    SERVER_PORT: int = 8000
    # PORT — приоритетная переменная (Railway / Heroku / etc).
    PORT: int | None = None

    # --- CryptoPanic (опционально; без ключа возможен публичный режим с лимитами) ---
    CRYPTOPANIC_API_KEY: str = ""

    # --- Фоновые задачи (polling): интервалы в секундах ---
    ETH_ALERT_CHECK_INTERVAL_SECONDS: int = 300
    DAILY_DIGEST_HOUR_UTC: int = 8
    DAILY_DIGEST_POLL_INTERVAL_SECONDS: int = 900

    # --- CoinGecko (публичный API, только чтение; ключ опционален на будущее) ---
    COINGECKO_BASE_URL: str = "https://api.coingecko.com/api/v3"

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_MODE: TelegramMode = "polling"
    TELEGRAM_WEBHOOK_URL: str = ""
    TELEGRAM_WEBHOOK_PATH: str = "/telegram/webhook"
    TELEGRAM_WEBHOOK_SECRET: str = ""

    # --- OpenRouter ---
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "openai/gpt-4.1-mini"
    OPENROUTER_SITE_URL: str = "https://example.com"
    OPENROUTER_APP_NAME: str = "Telegram AI Core"

    # --- Лимиты ---
    LLM_TIMEOUT_SECONDS: int = 120
    RATE_LIMIT_MESSAGES: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 3600
    DAILY_USER_MESSAGE_LIMIT: int = 0
    MONTHLY_GLOBAL_MESSAGE_LIMIT: int = 0
    AGENT_PROMPT_MAX_LENGTH: int = 8000

    # --- Database (полный набор поддерживаемых источников) ---
    DATABASE_URL: str = ""
    POSTGRES_URL: str = ""
    DATABASE_PRIVATE_URL: str = ""
    DATABASE_PUBLIC_URL: str = ""

    # Railway-стиль (libpq-совместимый набор).
    PGHOST: str = ""
    PGPORT: int | None = None
    PGUSER: str = ""
    PGPASSWORD: str = ""
    PGDATABASE: str = ""

    # Compose-стиль (текущий дефолт docker-compose).
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "telegram_ai_core"
    POSTGRES_USER: str = "telegram_ai_core"
    POSTGRES_PASSWORD: str = "telegram_ai_core_password"

    # --- Redis (полный набор поддерживаемых источников) ---
    REDIS_URL: str = ""
    REDIS_PRIVATE_URL: str = ""
    REDIS_PUBLIC_URL: str = ""

    REDISHOST: str = ""
    REDISPORT: int | None = None
    REDISUSER: str = ""
    REDISPASSWORD: str = ""

    # --- Diagnostics ---
    # Если задан, эндпоинт /diagnostics требует X-Diagnostics-Token.
    DIAGNOSTICS_TOKEN: str = ""

    # --- Admin / runtime settings (BD-overrides управляются через бот) ---
    BOT_ACCESS_MODE: BotAccessMode = "public"
    ALLOWED_TELEGRAM_USER_IDS_RAW: str = Field(
        "", alias="ALLOWED_TELEGRAM_USER_IDS"
    )
    ADMIN_TELEGRAM_IDS_RAW: str = Field("", alias="ADMIN_TELEGRAM_IDS")
    # Legacy alias: старое имя продолжает работать для /settings и admin-only.
    ADMIN_TELEGRAM_USER_IDS_RAW: str = Field("", alias="ADMIN_TELEGRAM_USER_IDS")
    # Опциональный Fernet-ключ для шифрования секретов в таблице app_settings.
    # Сгенерировать: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SETTINGS_ENCRYPTION_KEY: str | None = Field(default=None)

    # --- Telegram streaming renderer ---
    TELEGRAM_DRAFT_UPDATE_INTERVAL_MS: int = 500
    TELEGRAM_STREAM_MIN_CHARS_DELTA: int = 24
    TELEGRAM_STREAM_DRAFT_ENABLED: bool = True
    TELEGRAM_STREAM_EDIT_FALLBACK_ENABLED: bool = True
    # Backward-compatible aliases for older env/config names.
    TELEGRAM_DRAFT_MIN_INTERVAL_MS: int = 500
    TELEGRAM_MIN_DELTA_CHARS: int = 24
    TELEGRAM_CHAT_ACTION_INTERVAL_SECONDS: float = 4.0
    TELEGRAM_MESSAGE_MAX_CHARS: int = 3900

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------

    @property
    def effective_port(self) -> int:
        """Финальный порт сервиса. Приоритет: PORT > SERVER_PORT > 8000."""
        if self.PORT is not None:
            return int(self.PORT)
        if self.SERVER_PORT:
            return int(self.SERVER_PORT)
        return 8000

    # --- Postgres ---

    def _resolve_postgres(self) -> tuple[str, str]:
        """Возвращает (native_url, connection_source).

        Native URL — без +asyncpg, с префиксом postgresql://. Если ни один
        источник не сработал — ("", "none").
        """
        if self.DATABASE_URL:
            return normalize_to_native(self.DATABASE_URL), "DATABASE_URL"
        if self.POSTGRES_URL:
            return normalize_to_native(self.POSTGRES_URL), "POSTGRES_URL"
        if self.DATABASE_PRIVATE_URL:
            return (
                normalize_to_native(self.DATABASE_PRIVATE_URL),
                "DATABASE_PRIVATE_URL",
            )
        if self.DATABASE_PUBLIC_URL:
            return (
                normalize_to_native(self.DATABASE_PUBLIC_URL),
                "DATABASE_PUBLIC_URL",
            )

        # Railway-стиль libpq.
        if self.PGHOST and self.PGUSER and self.PGDATABASE:
            port = self.PGPORT or 5432
            user = quote_plus(self.PGUSER)
            password = quote_plus(self.PGPASSWORD or "")
            netloc = f"{user}:{password}@{self.PGHOST}:{port}" if password else (
                f"{user}@{self.PGHOST}:{port}"
            )
            return (
                f"postgresql://{netloc}/{self.PGDATABASE}",
                "PGHOST+PGPORT+PGUSER+PGPASSWORD+PGDATABASE",
            )

        # Compose-стиль (POSTGRES_*) — последний приоритет.
        if self.POSTGRES_HOST and self.POSTGRES_USER and self.POSTGRES_DB:
            user = quote_plus(self.POSTGRES_USER)
            password = quote_plus(self.POSTGRES_PASSWORD or "")
            netloc = (
                f"{user}:{password}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
                if password
                else f"{user}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
            )
            return (
                f"postgresql://{netloc}/{self.POSTGRES_DB}",
                "POSTGRES_HOST+POSTGRES_PORT+POSTGRES_USER+POSTGRES_PASSWORD+POSTGRES_DB",
            )

        return "", "none"

    @property
    def database_url_native(self) -> str:
        """Native PostgreSQL DSN без драйверного префикса (для asyncpg/psql)."""
        url, _ = self._resolve_postgres()
        return url

    @property
    def sqlalchemy_url(self) -> str:
        """DSN для async-SQLAlchemy (postgresql+asyncpg://...)."""
        url, _ = self._resolve_postgres()
        return normalize_to_asyncpg(url)

    @property
    def alembic_url(self) -> str:
        """DSN для Alembic.

        Alembic-env у нас работает через async_engine_from_config, так что
        нам нужен driver-prefix +asyncpg. При ручных операциях
        (alembic stamp / DDL-скрипты) можно взять database_url_native.
        """
        return self.sqlalchemy_url

    @property
    def effective_database_url(self) -> str:
        """Backward-compatible alias: DSN с asyncpg-драйвером."""
        return self.sqlalchemy_url

    @property
    def postgres_connection_source(self) -> str:
        """Источник, из которого собран DSN. 'none' — если не собрался."""
        _, source = self._resolve_postgres()
        return source

    # --- Redis ---

    def _resolve_redis(self) -> tuple[str, str]:
        """Возвращает (redis_url, connection_source)."""
        if self.REDIS_URL:
            return self.REDIS_URL, "REDIS_URL"
        if self.REDIS_PRIVATE_URL:
            return self.REDIS_PRIVATE_URL, "REDIS_PRIVATE_URL"
        if self.REDIS_PUBLIC_URL:
            return self.REDIS_PUBLIC_URL, "REDIS_PUBLIC_URL"

        if self.REDISHOST:
            port = self.REDISPORT or 6379
            user = quote_plus(self.REDISUSER) if self.REDISUSER else ""
            password = quote_plus(self.REDISPASSWORD) if self.REDISPASSWORD else ""
            if user or password:
                auth = f"{user}:{password}@" if password else f"{user}@"
            else:
                auth = ""
            return (
                f"redis://{auth}{self.REDISHOST}:{port}/0",
                "REDISHOST+REDISPORT+REDISUSER+REDISPASSWORD",
            )

        return "", "none"

    @property
    def effective_redis_url(self) -> str:
        url, _ = self._resolve_redis()
        return url

    @property
    def redis_connection_source(self) -> str:
        _, source = self._resolve_redis()
        return source

    # --- Connection sources (для diagnostics endpoint) ---

    @property
    def connection_sources(self) -> dict[str, str]:
        return {
            "postgres": self.postgres_connection_source,
            "redis": self.redis_connection_source,
        }

    @property
    def is_strict_env(self) -> bool:
        """В этих окружениях DATABASE_URL/REDIS_URL обязаны быть заданы."""
        return self.APP_ENV in {"railway", "production"}

    # --- Admin ---

    @property
    def allowed_telegram_user_ids(self) -> list[int]:
        """Парсит ALLOWED_TELEGRAM_USER_IDS (CSV) в список int."""
        return self._parse_csv_ints(self.ALLOWED_TELEGRAM_USER_IDS_RAW)

    @property
    def admin_telegram_user_ids(self) -> list[int]:
        """Парсит ADMIN_TELEGRAM_IDS и legacy ADMIN_TELEGRAM_USER_IDS.

        Невалидные значения молча пропускаются. Пустая строка — пустой список.
        """
        merged = [
            *self._parse_csv_ints(self.ADMIN_TELEGRAM_IDS_RAW),
            *self._parse_csv_ints(self.ADMIN_TELEGRAM_USER_IDS_RAW),
        ]
        out: list[int] = []
        seen: set[int] = set()
        for item in merged:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @staticmethod
    def _parse_csv_ints(raw_value: str | None) -> list[int]:
        raw = (raw_value or "").strip()
        if not raw:
            return []
        out: list[int] = []
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                out.append(int(item))
            except ValueError:
                continue
        return out

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate_for_strict_env(self) -> "Settings":
        """В railway/production падаем, если нет URL баз."""
        if self.is_strict_env:
            if not self.sqlalchemy_url:
                raise ConfigError(
                    "PostgreSQL connection is not configured. "
                    "Provide DATABASE_URL, POSTGRES_URL, DATABASE_PRIVATE_URL, "
                    "DATABASE_PUBLIC_URL, или PGHOST+PGPORT+PGUSER+PGPASSWORD+PGDATABASE."
                )
            if not self.effective_redis_url:
                raise ConfigError(
                    "Redis connection is not configured. "
                    "Provide REDIS_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL, "
                    "или REDISHOST+REDISPORT+REDISUSER+REDISPASSWORD."
                )
            log = logging.getLogger("config")
            if not self.TELEGRAM_BOT_TOKEN:
                log.warning(
                    "TELEGRAM_BOT_TOKEN is empty in strict env — polling will be disabled."
                )
            if not self.OPENROUTER_API_KEY:
                log.warning(
                    "OPENROUTER_API_KEY is empty in strict env — bot will not call LLM."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кешированный экземпляр Settings."""
    env_file = os.getenv("ENV_FILE")
    if env_file:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return Settings()


def reload_settings() -> Settings:
    """Сбрасывает кеш и возвращает свежие настройки. Использовать только в тестах."""
    get_settings.cache_clear()
    return get_settings()


__all__ = [
    "Settings",
    "ConfigError",
    "get_settings",
    "reload_settings",
    "mask_url_password",
    "normalize_to_asyncpg",
    "normalize_to_native",
]
