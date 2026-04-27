"""Async-сессии SQLAlchemy.

Глобальный async engine и async_sessionmaker инициализируются один раз
из FastAPI lifespan. Любой код, нуждающийся в БД, импортирует
``get_session_factory()`` или использует контекст-менеджер ``session_scope``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> AsyncEngine:
    """Создаёт глобальный AsyncEngine, если ещё не создан."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.effective_database_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set DATABASE_URL or POSTGRES_* env vars."
        )

    _engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    _session_factory = async_sessionmaker(
        bind=_engine, expire_on_commit=False, class_=AsyncSession
    )
    log.info("DB engine initialized")
    return _engine


async def dispose_engine() -> None:
    """Закрывает движок (в lifespan shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        log.info("DB engine disposed")
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Контекст-менеджер: открывает сессию, коммитит при выходе, откатывает на ошибке."""
    factory = get_session_factory()
    session: AsyncSession = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


__all__ = [
    "init_engine",
    "dispose_engine",
    "get_engine",
    "get_session_factory",
    "session_scope",
    "AsyncSession",
]
