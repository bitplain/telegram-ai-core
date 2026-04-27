"""Создание aiogram Dispatcher с подключением роутеров."""

from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers.commands import router as commands_router
from app.bot.handlers.messages import router as messages_router


def create_dispatcher() -> Dispatcher:
    """Возвращает Dispatcher с подключёнными роутерами."""
    dispatcher = Dispatcher()
    dispatcher.include_router(commands_router)
    dispatcher.include_router(messages_router)
    return dispatcher


__all__ = ["create_dispatcher"]
