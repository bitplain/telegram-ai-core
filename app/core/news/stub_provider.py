"""Stub: явно не подключает фейковые новости."""

from __future__ import annotations


class StubNewsProvider:
    """Пока нет RSS/API — честно сообщаем, что источники не подключены."""

    @property
    def sources_connected(self) -> bool:
        return False

    async def get_headlines(self, *, query: str, limit: int) -> list[str]:
        return []


__all__ = ["StubNewsProvider"]
