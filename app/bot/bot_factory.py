"""Создание aiogram Bot.

Если токен пустой — возвращаем None и пишем warning. Это позволяет
запускать FastAPI без Telegram (например, для health-check на CI).
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

log = logging.getLogger(__name__)


def create_bot(token: str | None) -> Bot | None:
    """Возвращает aiogram.Bot или None, если токен не задан."""
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN is empty — bot instance not created.")
        return None

    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


__all__ = ["create_bot"]
