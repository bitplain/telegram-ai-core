"""Схемы данных для новостного слоя."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Одна новость из внешнего источника (только реальные данные API/RSS)."""

    title: str
    source: str
    url: str
