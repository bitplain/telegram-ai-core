"""Создание aiogram Dispatcher с подключением роутеров."""

from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.access_control import AccessControlMiddleware
from app.bot.handlers.commands import router as commands_router
from app.bot.handlers.messages import router as messages_router
from app.bot.handlers.settings import settings_router


def create_dispatcher() -> Dispatcher:
    """Возвращает Dispatcher с MemoryStorage (для FSM admin /settings)
    и подключёнными роутерами.
    """
    # MemoryStorage достаточно: бот однопроцессный (polling/webhook),
    # state нужен только для краткосрочных диалогов (ввод API-ключа,
    # выбор модели). Persistent FSM не требуется.
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.message.middleware(AccessControlMiddleware())
    dispatcher.callback_query.middleware(AccessControlMiddleware())
    # settings_router подключаем первым, чтобы /settings перехватывал команду
    # до общих message-handler-ов.
    dispatcher.include_router(settings_router)
    dispatcher.include_router(commands_router)
    dispatcher.include_router(messages_router)
    return dispatcher


__all__ = ["create_dispatcher"]
