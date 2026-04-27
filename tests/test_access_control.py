"""Тесты access-control конфигурации Telegram-бота."""

from __future__ import annotations

import os
from typing import Iterable

import pytest

from app.config import Settings
from app.core.access_control import is_bot_access_allowed


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in (
        "BOT_ACCESS_MODE",
        "ALLOWED_TELEGRAM_USER_IDS",
        "ADMIN_TELEGRAM_IDS",
        "ADMIN_TELEGRAM_USER_IDS",
    ):
        monkeypatch.delenv(name, raising=False)
    empty_env = tmp_path / ".env.empty"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty_env))


def _set(monkeypatch: pytest.MonkeyPatch, items: Iterable[tuple[str, str]]) -> None:
    for name, value in items:
        monkeypatch.setenv(name, value)


def _settings() -> Settings:
    return Settings(_env_file=os.environ["ENV_FILE"])  # type: ignore[call-arg]


def test_public_allows_everyone() -> None:
    settings = _settings()
    assert settings.BOT_ACCESS_MODE == "public"
    assert is_bot_access_allowed(telegram_user_id=999, settings=settings) is True


def test_allowlist_allows_allowed_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("BOT_ACCESS_MODE", "allowlist"),
            ("ALLOWED_TELEGRAM_USER_IDS", "100,200"),
        ],
    )
    settings = _settings()
    assert settings.allowed_telegram_user_ids == [100, 200]
    assert is_bot_access_allowed(telegram_user_id=200, settings=settings) is True


def test_allowlist_allows_admin_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("BOT_ACCESS_MODE", "allowlist"),
            ("ADMIN_TELEGRAM_IDS", "777"),
        ],
    )
    settings = _settings()
    assert settings.admin_telegram_user_ids == [777]
    assert is_bot_access_allowed(telegram_user_id=777, settings=settings) is True


def test_allowlist_denies_unknown_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("BOT_ACCESS_MODE", "allowlist"),
            ("ALLOWED_TELEGRAM_USER_IDS", "100"),
            ("ADMIN_TELEGRAM_IDS", "777"),
        ],
    )
    assert is_bot_access_allowed(telegram_user_id=555, settings=_settings()) is False


def test_admin_only_allows_only_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("BOT_ACCESS_MODE", "admin_only"),
            ("ALLOWED_TELEGRAM_USER_IDS", "100"),
            ("ADMIN_TELEGRAM_IDS", "777"),
        ],
    )
    settings = _settings()
    assert is_bot_access_allowed(telegram_user_id=777, settings=settings) is True
    assert is_bot_access_allowed(telegram_user_id=100, settings=settings) is False


def test_legacy_admin_env_is_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        [
            ("ADMIN_TELEGRAM_IDS", "111"),
            ("ADMIN_TELEGRAM_USER_IDS", "222,111"),
        ],
    )
    assert _settings().admin_telegram_user_ids == [111, 222]

