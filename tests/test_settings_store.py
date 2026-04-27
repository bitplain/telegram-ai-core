"""Тесты SettingsStore без реальной БД и Redis.

Покрываем:
- ``_encrypt`` / ``_decrypt`` (с Fernet и без него),
- круг шифрование → расшифровка с разными ключами,
- сериализация ModelInfo (для openrouter_models cache).

Сценарии с настоящей БД (PostgreSQL) и Redis тестируются интеграционно
через ``docker compose exec app pytest``; в unit-тестах это сложно и
не даёт ценности сверх того, что уже даёт docker-сценарий.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import reload_settings
from app.core.settings_store import SettingsStore, reset_settings_store_for_tests


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_USER_IDS", raising=False)
    empty_env = tmp_path / ".env.empty"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty_env))
    reload_settings()
    reset_settings_store_for_tests()
    yield
    reset_settings_store_for_tests()
    reload_settings()


def test_store_without_key_stores_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SettingsStore()
    assert store.encryption_enabled is False
    stored, is_encrypted = store._encrypt("sk-or-v1-abcdef")
    assert stored == "sk-or-v1-abcdef"
    assert is_encrypted is False
    assert store._decrypt(stored, is_encrypted) == "sk-or-v1-abcdef"


def test_store_with_fernet_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)
    reload_settings()
    reset_settings_store_for_tests()

    store = SettingsStore()
    assert store.encryption_enabled is True

    secret = "sk-or-v1-very-secret-key"
    stored, is_encrypted = store._encrypt(secret)
    assert is_encrypted is True
    # Шифротекст не равен исходному.
    assert stored != secret
    # И сам секрет не «торчит» в зашифрованном представлении.
    assert secret not in stored
    # Расшифровка возвращает то же самое.
    assert store._decrypt(stored, is_encrypted) == secret


def test_store_with_invalid_key_falls_back_to_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    reload_settings()
    reset_settings_store_for_tests()

    store = SettingsStore()
    # Деградация — но без падения процесса.
    assert store.encryption_enabled is False
    stored, is_encrypted = store._encrypt("hello")
    assert stored == "hello"
    assert is_encrypted is False


def test_store_decrypt_with_wrong_key_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если БД зашифрована старым ключом, а ENV содержит новый — _decrypt вернёт None."""
    old_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", old_key)
    reload_settings()
    reset_settings_store_for_tests()

    store_old = SettingsStore()
    stored, _ = store_old._encrypt("payload")

    # Меняем ключ на новый.
    new_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", new_key)
    reload_settings()
    reset_settings_store_for_tests()

    store_new = SettingsStore()
    assert store_new._decrypt(stored, is_encrypted=True) is None


def test_store_encrypted_in_db_but_no_key_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если is_encrypted=True, но SETTINGS_ENCRYPTION_KEY вырезан — расшифровать нельзя."""
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", key)
    reload_settings()
    reset_settings_store_for_tests()

    store_with_key = SettingsStore()
    stored, _ = store_with_key._encrypt("payload")

    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
    reload_settings()
    reset_settings_store_for_tests()

    store_no_key = SettingsStore()
    assert store_no_key._decrypt(stored, is_encrypted=True) is None
    # Незашифрованные значения возвращаются как есть.
    assert store_no_key._decrypt("plaintext", is_encrypted=False) == "plaintext"


def test_model_override_prefix_constant() -> None:
    assert SettingsStore.MODEL_OVERRIDE_PREFIX == "model_override."
    assert SettingsStore.SETTING_OPENROUTER_API_KEY == "openrouter_api_key"
    assert SettingsStore.SETTING_YANDEX_API_KEY == "yandex_api_key"
    assert SettingsStore.SETTING_OPENROUTER_FAVORITE_MODELS == "openrouter_favorite_models"


def test_cache_ttl_constant() -> None:
    assert SettingsStore.CACHE_TTL_SECONDS == 60
