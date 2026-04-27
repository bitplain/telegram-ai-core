"""Тесты парсинга ADMIN_TELEGRAM_USER_IDS и AdminFilter."""

from __future__ import annotations

import os
from typing import Iterable

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Изолируемся от .env: пустой ENV_FILE + удалённые admin переменные."""
    monkeypatch.delenv("ADMIN_TELEGRAM_USER_IDS", raising=False)
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
    empty_env = tmp_path / ".env.empty"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty_env))


def _set(monkeypatch: pytest.MonkeyPatch, items: Iterable[tuple[str, str]]) -> None:
    for name, value in items:
        monkeypatch.setenv(name, value)


def _make_settings() -> Settings:
    env_file = os.environ.get("ENV_FILE")
    if env_file:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return Settings()


def test_admin_telegram_user_ids_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, [("ADMIN_TELEGRAM_USER_IDS", "123,456,789")])
    s = _make_settings()
    assert s.admin_telegram_user_ids == [123, 456, 789]


def test_admin_telegram_user_ids_handles_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, [("ADMIN_TELEGRAM_USER_IDS", " 100 , 200,  300 ")])
    s = _make_settings()
    assert s.admin_telegram_user_ids == [100, 200, 300]


def test_admin_telegram_user_ids_empty() -> None:
    s = _make_settings()
    assert s.admin_telegram_user_ids == []


def test_admin_telegram_user_ids_skips_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, [("ADMIN_TELEGRAM_USER_IDS", "abc,123,xyz,  ,456")])
    s = _make_settings()
    assert s.admin_telegram_user_ids == [123, 456]


def test_admin_telegram_user_ids_single_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set(monkeypatch, [("ADMIN_TELEGRAM_USER_IDS", "777")])
    s = _make_settings()
    assert s.admin_telegram_user_ids == [777]


def test_admin_filter_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """AdminFilter спрашивает get_settings(), значит должен видеть ровно
    то, что отдаёт ``settings.admin_telegram_user_ids``.

    Здесь же проверяем, что фильтр без user-а возвращает False.
    """
    import asyncio

    from app.bot.filters.admin import AdminFilter
    from app.config import reload_settings

    _set(monkeypatch, [("ADMIN_TELEGRAM_USER_IDS", "555,666")])
    reload_settings()

    class _User:
        def __init__(self, uid: int) -> None:
            self.id = uid

    class _Event:
        def __init__(self, user: _User | None) -> None:
            self.from_user = user

    flt = AdminFilter()
    assert asyncio.run(flt(_Event(_User(555)))) is True  # type: ignore[arg-type]
    assert asyncio.run(flt(_Event(_User(123)))) is False  # type: ignore[arg-type]
    assert asyncio.run(flt(_Event(None))) is False  # type: ignore[arg-type]
    # Возвращаем кеш в дефолт.
    monkeypatch.delenv("ADMIN_TELEGRAM_USER_IDS", raising=False)
    reload_settings()
