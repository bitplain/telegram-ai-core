"""Webhook HTTP behavior (secret, disabled mode)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.telegram_webhook import router
from app.config import reload_settings
from fastapi import FastAPI


@pytest.fixture
def webhook_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FastAPI:
    empty_env = tmp_path / ".env.wh"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(empty_env))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://u:p@127.0.0.1:65432/telegram_ai_core",
    )
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    reload_settings()

    app = FastAPI()
    app.include_router(router)

    bot = MagicMock()
    dp = MagicMock()
    dp.feed_update = AsyncMock()
    app.state.bot = bot
    app.state.dispatcher = dp
    return app


@pytest.mark.asyncio
async def test_webhook_wrong_secret_returns_403(
    webhook_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.telegram_webhook as wh

    class S:
        TELEGRAM_MODE = "webhook"
        TELEGRAM_WEBHOOK_SECRET = "correct"

    monkeypatch.setattr(wh, "get_settings", lambda: S())

    transport = ASGITransport(app=webhook_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_webhook_polling_mode_returns_410(
    webhook_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.telegram_webhook as wh

    class S:
        TELEGRAM_MODE = "polling"
        TELEGRAM_WEBHOOK_SECRET = "x"

    monkeypatch.setattr(wh, "get_settings", lambda: S())

    transport = ASGITransport(app=webhook_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/telegram/webhook", json={})
    assert r.status_code == 410
