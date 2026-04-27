"""Application configuration via pydantic-settings v2.

Все настройки приходят из переменных окружения / .env-файла.
Никакие секреты в коде не хранятся и не логируются.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Поднимается, если конфигурация некорректна для прод-окружений."""


AppEnv = Literal["local", "railway", "production"]
TelegramMode = Literal["polling", "webhook"]


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

    # --- Database ---
    DATABASE_URL: str = ""
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "telegram_ai_core"
    POSTGRES_USER: str = "telegram_ai_core"
    POSTGRES_PASSWORD: str = "telegram_ai_core_password"

    # --- Redis ---
    REDIS_URL: str = ""

    # --- Renderer ---
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

    @property
    def effective_database_url(self) -> str:
        """Возвращает фактический DATABASE_URL с asyncpg-драйвером.

        Если переменная не задана, собираем из POSTGRES_*.
        """
        if self.DATABASE_URL:
            return self._normalize_database_url(self.DATABASE_URL)

        if not (self.POSTGRES_HOST and self.POSTGRES_DB and self.POSTGRES_USER):
            return ""

        password = quote_plus(self.POSTGRES_PASSWORD or "")
        user = quote_plus(self.POSTGRES_USER)
        return (
            f"postgresql+asyncpg://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @staticmethod
    def _normalize_database_url(url: str) -> str:
        """Заменяет схему на postgresql+asyncpg, если она не задана явно.

        Railway/Heroku обычно отдают postgresql:// — асинхронный движок
        SQLAlchemy требует драйверный префикс.
        """
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://") :]
        return url

    @property
    def is_strict_env(self) -> bool:
        """В этих окружениях DATABASE_URL/REDIS_URL обязаны быть заданы."""
        return self.APP_ENV in {"railway", "production"}

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate_for_strict_env(self) -> "Settings":
        """В railway/production падаем, если нет URL баз."""
        if self.is_strict_env:
            if not self.effective_database_url:
                raise ConfigError(
                    "DATABASE_URL is required when APP_ENV=railway/production."
                )
            if not self.REDIS_URL:
                raise ConfigError(
                    "REDIS_URL is required when APP_ENV=railway/production."
                )
            # Токены — только warning через логгер, не падаем.
            log = logging.getLogger("config")
            if not self.TELEGRAM_BOT_TOKEN:
                log.warning("TELEGRAM_BOT_TOKEN is empty in strict env — polling will be disabled.")
            if not self.OPENROUTER_API_KEY:
                log.warning("OPENROUTER_API_KEY is empty in strict env — bot will not call LLM.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает кешированный экземпляр Settings."""
    # pydantic-settings сам читает .env. На некоторых платформах удобно
    # переопределить файл через ENV_FILE — поддержим это, не ломая поведения.
    env_file = os.getenv("ENV_FILE")
    if env_file:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return Settings()


def reload_settings() -> Settings:
    """Сбрасывает кеш и возвращает свежие настройки. Использовать только в тестах."""
    get_settings.cache_clear()
    return get_settings()
