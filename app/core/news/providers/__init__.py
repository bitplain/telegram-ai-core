"""Провайдеры внешних новостей (CryptoPanic, RSS)."""

from __future__ import annotations

from app.core.news.providers.aggregate import fetch_crypto_news
from app.core.news.providers.base import NewsProvider

__all__ = ["NewsProvider", "fetch_crypto_news"]
