"""Общие типы для новостных провайдеров."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    url: str


__all__ = ["NewsItem"]
