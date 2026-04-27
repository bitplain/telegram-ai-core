"""Запуск aiogram polling в виде корутины, удобной для FastAPI lifespan."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher

log = logging.getLogger(__name__)


async def start_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    """Стартует long-polling и корректно закрывает сессию при завершении."""
    log.info("Starting Telegram long-polling")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, handle_signals=False)
    except Exception:  # noqa: BLE001
        # Падать в lifespan мы не хотим — handler сам залогирует. Здесь оставим
        # запись, чтобы Railway/Compose увидели причину остановки polling.
        log.exception("Telegram polling stopped due to error")
        raise
    finally:
        try:
            await bot.session.close()
        except Exception:  # noqa: BLE001
            log.warning("Error while closing bot session")
        log.info("Telegram long-polling stopped")


__all__ = ["start_polling"]
