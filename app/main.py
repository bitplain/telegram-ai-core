"""FastAPI entrypoint.

Lifespan:
- настраиваем JSON-логирование;
- инициализируем DB engine и Redis;
- если TELEGRAM_MODE=polling и токен задан — стартуем aiogram polling в задаче;
- shutdown: cancel polling, dispose engine, close redis, close httpx-клиенты.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.diagnostics import router as diagnostics_router
from app.api.health import router as health_router
from app.api.telegram_webhook import router as telegram_webhook_router
from app.bot.bot_factory import create_bot
from app.bot.dispatcher import create_dispatcher
from app.bot.polling import start_polling
from app.config import get_settings
from app.db.session import dispose_engine, init_engine
from app.llm.openrouter_client import close_openrouter_client
from app.logging_config import setup_logging
from app.redis.client import close_redis, init_redis

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    log.info(
        "Starting Telegram AI Core",
        extra={
            "app_env": settings.APP_ENV,
            "telegram_mode": settings.TELEGRAM_MODE,
            "openrouter_model": settings.OPENROUTER_MODEL,
        },
    )

    init_engine()
    await init_redis()

    bot = None
    dispatcher = None
    polling_task: asyncio.Task | None = None

    if settings.TELEGRAM_BOT_TOKEN:
        bot = create_bot(settings.TELEGRAM_BOT_TOKEN)
        if bot is not None:
            dispatcher = create_dispatcher()
            app.state.bot = bot
            app.state.dispatcher = dispatcher

            if settings.TELEGRAM_MODE == "polling":
                polling_task = asyncio.create_task(
                    start_polling(bot, dispatcher), name="telegram-polling"
                )
                log.info("Telegram polling task started")
            else:
                log.info("Telegram mode=webhook — polling not started")
        else:
            log.warning("Failed to create bot instance")
    else:
        log.warning("TELEGRAM_BOT_TOKEN is empty, polling is disabled.")

    try:
        yield
    finally:
        log.info("Shutting down")
        if polling_task is not None:
            polling_task.cancel()
            try:
                await polling_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                # CancelledError ожидаем; прочие ошибки уже залогированы в polling.
                pass

        if bot is not None:
            try:
                await bot.session.close()
            except Exception:  # noqa: BLE001
                log.warning("Error while closing bot session in lifespan")

        await close_openrouter_client()
        await close_redis()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Telegram AI Core",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.include_router(health_router)
    app.include_router(diagnostics_router)
    app.include_router(telegram_webhook_router)
    return app


app = create_app()
