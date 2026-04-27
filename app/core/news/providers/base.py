"""Базовый контракт провайдера новостей."""

from __future__ import annotations

from typing import Protocol

from app.core.news.schemas import NewsItem


class NewsProvider(Protocol):
    """Асинхронный источник новостей."""

    async def fetch_items(self, *, limit: int) -> list[NewsItem]:
        """Возвращает до ``limit`` элементов или пустой список при ошибке."""
        ...
