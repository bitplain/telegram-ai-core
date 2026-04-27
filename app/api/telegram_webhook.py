"""Telegram webhook: validates secret, feeds updates to aiogram dispatcher."""

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
        return JSONResponse(
            {"detail": "webhook mode is not enabled"},
            status_code=410,
        )

    secret = (settings.TELEGRAM_WEBHOOK_SECRET or "").strip()
    if not secret:
        log.warning("TELEGRAM_WEBHOOK_SECRET is empty while in webhook mode")
        raise HTTPException(status_code=503, detail="webhook secret not configured")

    if x_telegram_bot_api_secret_token != secret:
        raise HTTPException(status_code=403, detail="invalid secret token")

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
