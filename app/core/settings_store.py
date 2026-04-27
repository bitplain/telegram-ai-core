"""Хранилище runtime-настроек: model overrides и прочие не-секретные ключи.

OpenRouter и прочие provider API keys **не** хранятся в БД — только в ENV.

Слои:
1. Redis-кеш (TTL 60s).
2. PostgreSQL ``app_settings`` — источник истины для overrides.

Шифрование (Fernet) включается, если задан ``SETTINGS_ENCRYPTION_KEY``;
для Yandex API key (заглушка) применяется то же шифрование.

Singleton: ``get_settings_store()``. Все методы — async.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models import AppSetting
from app.db.session import session_scope
from app.redis.client import get_redis

log = logging.getLogger(__name__)


class SettingsStore:
    """Async-обёртка над таблицей ``app_settings`` с Redis-кешем."""

    SETTING_YANDEX_API_KEY = "yandex_api_key"
    SETTING_OPENROUTER_FAVORITE_MODELS = "openrouter_favorite_models"
    MODEL_OVERRIDE_PREFIX = "model_override."
    CACHE_TTL_SECONDS = 60
    _CACHE_NAMESPACE = "app_settings:v1:"
    _NULL_SENTINEL = "\x00null\x00"

    def __init__(self) -> None:
        self._fernet: Fernet | None = self._build_fernet()

    @staticmethod
    def _build_fernet() -> Fernet | None:
        settings = get_settings()
        key = (settings.SETTINGS_ENCRYPTION_KEY or "").strip()
        if not key:
            return None
        try:
            return Fernet(key.encode("utf-8"))
        except Exception:  # noqa: BLE001
            log.exception(
                "SETTINGS_ENCRYPTION_KEY is set but invalid; secrets will be stored in plaintext"
            )
            return None

    @property
    def encryption_enabled(self) -> bool:
        return self._fernet is not None

    async def get_yandex_api_key(self) -> str | None:
        """Актуальный Yandex API key из БД (ENV-fallback не используется)."""
        cached = await self._cache_get(self.SETTING_YANDEX_API_KEY)
        if cached is not None:
            return cached if cached != self._NULL_SENTINEL else None

        value, is_encrypted = await self._db_get(self.SETTING_YANDEX_API_KEY)
        if value is None:
            await self._cache_set(self.SETTING_YANDEX_API_KEY, self._NULL_SENTINEL)
            return None

        decrypted = self._decrypt(value, is_encrypted)
        if decrypted is not None:
            await self._cache_set(self.SETTING_YANDEX_API_KEY, decrypted)
            return decrypted

        await self._cache_set(self.SETTING_YANDEX_API_KEY, self._NULL_SENTINEL)
        return None

    async def has_db_yandex_api_key(self) -> bool:
        """True, если Yandex API ключ задан в БД."""
        value, _ = await self._db_get(self.SETTING_YANDEX_API_KEY)
        return value is not None and value != ""

    async def set_yandex_api_key(self, value: str, by_user_id: int) -> None:
        """Сохраняет Yandex API ключ (пока заглушка для будущей интеграции)."""
        stored, is_encrypted = self._encrypt(value)
        await self._db_upsert(
            key=self.SETTING_YANDEX_API_KEY,
            value=stored,
            is_encrypted=is_encrypted,
            by_user_id=by_user_id,
        )
        await self._cache_invalidate(self.SETTING_YANDEX_API_KEY)

    async def list_openrouter_favorite_models(self) -> list[str]:
        """Возвращает сохранённые OpenRouter slug-и избранных моделей."""
        cached = await self._cache_get(self.SETTING_OPENROUTER_FAVORITE_MODELS)
        if cached is not None:
            return self._parse_favorite_models(cached)

        value, is_encrypted = await self._db_get(
            self.SETTING_OPENROUTER_FAVORITE_MODELS
        )
        if value is None:
            await self._cache_set(self.SETTING_OPENROUTER_FAVORITE_MODELS, "[]")
            return []
        decrypted = self._decrypt(value, is_encrypted)
        models = self._parse_favorite_models(decrypted or "[]")
        await self._cache_set(
            self.SETTING_OPENROUTER_FAVORITE_MODELS,
            json.dumps(models, ensure_ascii=False),
        )
        return models

    async def set_openrouter_favorite_models(
        self, model_ids: list[str], by_user_id: int
    ) -> None:
        """Сохраняет избранные OpenRouter model slug-и без дублей и пустых значений."""
        normalized = self._normalize_favorite_models(model_ids)
        await self._db_upsert(
            key=self.SETTING_OPENROUTER_FAVORITE_MODELS,
            value=json.dumps(normalized, ensure_ascii=False),
            is_encrypted=False,
            by_user_id=by_user_id,
        )
        await self._cache_invalidate(self.SETTING_OPENROUTER_FAVORITE_MODELS)

    async def toggle_openrouter_favorite_model(
        self, model_id: str, by_user_id: int
    ) -> tuple[bool, list[str]]:
        """Переключает модель в избранном. Возвращает (added, current_list)."""
        model_id = (model_id or "").strip()
        current = await self.list_openrouter_favorite_models()
        if not model_id:
            return False, current
        if model_id in current:
            current = [item for item in current if item != model_id]
            added = False
        else:
            current.append(model_id)
            added = True
        await self.set_openrouter_favorite_models(current, by_user_id=by_user_id)
        return added, current

    async def add_openrouter_favorite_model(
        self, model_id: str, by_user_id: int
    ) -> list[str]:
        """Добавляет OpenRouter model slug в избранное идемпотентно."""
        model_id = (model_id or "").strip()
        current = await self.list_openrouter_favorite_models()
        if model_id and model_id not in current:
            current.append(model_id)
            await self.set_openrouter_favorite_models(current, by_user_id=by_user_id)
        return current

    async def remove_openrouter_favorite_model(
        self, model_id: str, by_user_id: int
    ) -> list[str]:
        """Удаляет OpenRouter model slug из избранного идемпотентно."""
        model_id = (model_id or "").strip()
        current = await self.list_openrouter_favorite_models()
        if model_id and model_id in current:
            current = [item for item in current if item != model_id]
            await self.set_openrouter_favorite_models(current, by_user_id=by_user_id)
        return current

    async def get_model_override(self, model_id: str) -> str | None:
        """Возвращает OpenRouter slug-override для ModelProfile, либо None."""
        if not model_id:
            return None
        full_key = f"{self.MODEL_OVERRIDE_PREFIX}{model_id}"

        cached = await self._cache_get(full_key)
        if cached is not None:
            return cached if cached != self._NULL_SENTINEL else None

        value, is_encrypted = await self._db_get(full_key)
        if value is None:
            await self._cache_set(full_key, self._NULL_SENTINEL)
            return None

        decrypted = self._decrypt(value, is_encrypted)
        if decrypted:
            await self._cache_set(full_key, decrypted)
        else:
            await self._cache_set(full_key, self._NULL_SENTINEL)
        return decrypted or None

    async def set_model_override(
        self, model_id: str, model_name: str, by_user_id: int
    ) -> None:
        if not model_id or not model_name:
            return
        full_key = f"{self.MODEL_OVERRIDE_PREFIX}{model_id}"
        await self._db_upsert(
            key=full_key,
            value=model_name,
            is_encrypted=False,
            by_user_id=by_user_id,
        )
        await self._cache_invalidate(full_key)

    async def list_model_overrides(self) -> dict[str, str]:
        """Возвращает {model_id: model_name} для всех текущих overrides."""
        async with session_scope() as session:
            stmt = select(AppSetting).where(
                AppSetting.key.like(f"{self.MODEL_OVERRIDE_PREFIX}%")
            )
            rows = (await session.execute(stmt)).scalars().all()
        out: dict[str, str] = {}
        for row in rows:
            short_key = row.key[len(self.MODEL_OVERRIDE_PREFIX) :]
            decrypted = self._decrypt(row.value, row.is_encrypted)
            if decrypted:
                out[short_key] = decrypted
        return out

    async def reset_all_overrides(self) -> None:
        """Удаляет все model_override.* записи и инвалидирует их кеш."""
        async with session_scope() as session:
            stmt_select = select(AppSetting.key).where(
                AppSetting.key.like(f"{self.MODEL_OVERRIDE_PREFIX}%")
            )
            keys = list((await session.execute(stmt_select)).scalars().all())
            await session.execute(
                delete(AppSetting).where(
                    AppSetting.key.like(f"{self.MODEL_OVERRIDE_PREFIX}%")
                )
            )
        for key in keys:
            await self._cache_invalidate(key)

    @staticmethod
    def _normalize_favorite_models(model_ids: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in model_ids:
            value = (raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    @classmethod
    def _parse_favorite_models(cls, raw: str) -> list[str]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return cls._normalize_favorite_models([str(item) for item in data])

    def _encrypt(self, value: str) -> tuple[str, bool]:
        """Возвращает (stored_value, is_encrypted_flag)."""
        if self._fernet is None:
            log.warning(
                "SETTINGS_ENCRYPTION_KEY is not set — storing secret in plaintext"
            )
            return value, False
        token = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return token, True

    def _decrypt(self, stored: str, is_encrypted: bool) -> str | None:
        if not is_encrypted:
            return stored
        if self._fernet is None:
            log.error(
                "Encrypted setting in DB but SETTINGS_ENCRYPTION_KEY is not set; cannot decrypt"
            )
            return None
        try:
            return self._fernet.decrypt(stored.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            log.error("Failed to decrypt app_settings value (InvalidToken)")
            return None
        except Exception:  # noqa: BLE001
            log.exception("Unexpected error while decrypting app_settings value")
            return None

    @staticmethod
    async def _db_get(key: str) -> tuple[str | None, bool]:
        async with session_scope() as session:
            stmt = select(AppSetting).where(AppSetting.key == key)
            row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None, False
        return row.value, bool(row.is_encrypted)

    @staticmethod
    async def _db_upsert(
        *,
        key: str,
        value: str,
        is_encrypted: bool,
        by_user_id: int | None,
    ) -> None:
        async with session_scope() as session:
            stmt = select(AppSetting).where(AppSetting.key == key)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if existing is None:
                session.add(
                    AppSetting(
                        key=key,
                        value=value,
                        is_encrypted=is_encrypted,
                        updated_at=now,
                        updated_by_telegram_user_id=by_user_id,
                    )
                )
            else:
                existing.value = value
                existing.is_encrypted = is_encrypted
                existing.updated_at = now
                existing.updated_by_telegram_user_id = by_user_id

    async def _cache_get(self, key: str) -> str | None:
        client = get_redis()
        if client is None:
            return None
        try:
            value: Any = await client.get(self._CACHE_NAMESPACE + key)
        except Exception:  # noqa: BLE001
            log.debug("Redis GET failed for %s; degrading to DB", key, exc_info=True)
            return None
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def _cache_set(self, key: str, value: str) -> None:
        client = get_redis()
        if client is None:
            return
        try:
            await client.set(
                self._CACHE_NAMESPACE + key,
                value,
                ex=self.CACHE_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001
            log.debug("Redis SET failed for %s; ignoring", key, exc_info=True)

    async def _cache_invalidate(self, key: str) -> None:
        client = get_redis()
        if client is None:
            return
        try:
            await client.delete(self._CACHE_NAMESPACE + key)
        except Exception:  # noqa: BLE001
            log.debug("Redis DEL failed for %s; ignoring", key, exc_info=True)


_singleton: SettingsStore | None = None


def get_settings_store() -> SettingsStore:
    """Singleton-инстанс. Перечитывает Fernet-ключ только при перезапуске процесса."""
    global _singleton
    if _singleton is None:
        _singleton = SettingsStore()
    return _singleton


def reset_settings_store_for_tests() -> None:
    """Сбрасывает singleton (используется только в тестах)."""
    global _singleton
    _singleton = None


__all__ = [
    "SettingsStore",
    "get_settings_store",
    "reset_settings_store_for_tests",
]
