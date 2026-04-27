"""Endpoint для Telegram webhook (заложен, но MVP работает в polling-режиме).

Если ``TELEGRAM_MODE=webhook`` и заданы ``TELEGRAM_WEBHOOK_URL`` и
``TELEGRAM_WEBHOOK_SECRET``, FastAPI принимает апдейты по
``TELEGRAM_WEBHOOK_PATH`` и проксирует их в aiogram-диспетчер.

Для MVP реализация компактная — нужна, чтобы маршрут существовал и проходил
валидацию заголовка X-Telegram-Bot-Api-Secret-Token.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request
from starlette.responses import JSONResponse

from app.config import get_settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    settings = get_settings()

    if settings.TELEGRAM_MODE != "webhook":
        # MVP режим — webhook не активен. Возвращаем 200 без обработки,
        # чтобы Telegram не ретраил.
        return JSONResponse({"status": "disabled"}, status_code=200)

    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="invalid secret token")

    bot: Bot | None = getattr(request.app.state, "bot", None)
    dispatcher: Dispatcher | None = getattr(request.app.state, "dispatcher", None)
    if bot is None or dispatcher is None:
        log.warning("Telegram webhook called but bot/dispatcher are not initialized")
        raise HTTPException(status_code=503, detail="bot is not configured")

    payload = await request.json()
    try:
        update = Update.model_validate(payload, context={"bot": bot})
    except Exception as exc:  # noqa: BLE001
        log.warning("Invalid Telegram update payload: %s", exc.__class__.__name__)
        raise HTTPException(status_code=400, detail="invalid payload") from exc

    await dispatcher.feed_update(bot, update)
    return JSONResponse({"status": "ok"})


__all__ = ["router"]
