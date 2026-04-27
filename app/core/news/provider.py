"""Абстракция поставщика новостей: только реальные источники, без выдумок."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.news.stub_provider import StubNewsProvider


@runtime_checkable
class NewsProvider(Protocol):
    """Провайдер новостей. Если источники не настроены — ``sources_connected`` False."""

    @property
    def sources_connected(self) -> bool:
        """True, если к боту подключены реальные фиды/API."""

    async def get_headlines(self, *, query: str, limit: int) -> list[str]:
        """Заголовки из подключённых источников; пусто, если нечего отдать."""


def get_news_provider() -> NewsProvider:
    """Текущая реализация: заглушка с явным статусом «источники не подключены»."""
    return _STUB


_STUB = StubNewsProvider()

__all__ = ["NewsProvider", "get_news_provider"]
