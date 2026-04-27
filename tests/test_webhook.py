"""Telegram webhook URL and secret validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.telegram_webhook import router as telegram_webhook_router


@pytest.fixture
def webhook_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    from app.config import reload_settings

    empty = tmp_path / ".env.empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TELEGRAM_MODE", "webhook")
    monkeypatch.setenv("PUBLIC_API_URL", "https://example.com")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "correct-secret-token")
    reload_settings()

    app = FastAPI()
    app.include_router(telegram_webhook_router)
    app.state.bot = MagicMock()
    dp = MagicMock()
    dp.feed_update = AsyncMock()
    app.state.dispatcher = dp
    return TestClient(app, raise_server_exceptions=True)


def test_webhook_url_built_from_public_api_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.config import Settings, reload_settings

    empty = tmp_path / ".env.empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty))
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com/")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
    reload_settings()
    s = Settings(_env_file=str(empty))  # type: ignore[call-arg]
    assert s.telegram_webhook_full_url == "https://api.example.com/telegram/webhook"


def test_webhook_wrong_secret_returns_403(webhook_app: TestClient) -> None:
    r = webhook_app.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert r.status_code == 403


def test_webhook_missing_secret_returns_403(webhook_app: TestClient) -> None:
    r = webhook_app.post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 403


def test_webhook_correct_secret_ok(webhook_app: TestClient) -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1710000000,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "text": "hi",
        },
    }
    r = webhook_app.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "correct-secret-token"},
    )
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
