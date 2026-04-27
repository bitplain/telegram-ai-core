"""AdminFilter: пропускает только Telegram-пользователей из admin ids."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import get_settings


class AdminFilter(BaseFilter):
    """True, если ``event.from_user.id`` входит в ``settings.admin_telegram_user_ids``.

    Используется для всех handler-ов команды ``/settings`` и её callback-ов.
    Список администраторов берётся из ENV ``ADMIN_TELEGRAM_IDS`` и legacy
    ``ADMIN_TELEGRAM_USER_IDS``.
    """

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if event.from_user is None:
            return False
        admin_ids = get_settings().admin_telegram_user_ids
        if not admin_ids:
            return False
        return event.from_user.id in admin_ids


__all__ = ["AdminFilter"]
