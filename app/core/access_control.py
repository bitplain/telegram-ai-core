"""Access-control для Telegram updates."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from app.bot.renderers.telegram_text import send_plain
from app.config import Settings, get_settings

log = logging.getLogger(__name__)

ACCESS_DENIED_MESSAGE = "Доступ к боту ограничен."


def is_bot_access_allowed(*, telegram_user_id: int, settings: Settings) -> bool:
    """Возвращает True, если пользователь может пользоваться ботом."""
    mode = settings.BOT_ACCESS_MODE
    admin_ids = set(settings.admin_telegram_user_ids)
    allowed_ids = set(settings.allowed_telegram_user_ids)

    if mode == "public":
        return True
    if mode == "allowlist":
        return telegram_user_id in allowed_ids or telegram_user_id in admin_ids
    if mode == "admin_only":
        return telegram_user_id in admin_ids
    return False


class AccessControlMiddleware(BaseMiddleware):
    """Aiogram middleware, который отсекает пользователей до handlers."""

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None:
            return await handler(event, data)

        settings = get_settings()
        if is_bot_access_allowed(telegram_user_id=user.id, settings=settings):
            return await handler(event, data)
        if isinstance(event, Message) and _is_debug_command(event.text):
            return await handler(event, data)

        log.info(
            "access_denied",
            extra={
                "telegram_user_id": user.id,
                "bot_access_mode": settings.BOT_ACCESS_MODE,
            },
        )
        if isinstance(event, CallbackQuery):
            await event.answer(ACCESS_DENIED_MESSAGE, show_alert=True)
            return None
        await send_plain(event.bot, event.chat.id, ACCESS_DENIED_MESSAGE)
        return None


def _is_debug_command(text: str | None) -> bool:
    if not text:
        return False
    command = text.strip().split(maxsplit=1)[0].lower()
    return command == "/debug" or command.startswith("/debug@")


__all__ = [
    "ACCESS_DENIED_MESSAGE",
    "AccessControlMiddleware",
    "is_bot_access_allowed",
]
