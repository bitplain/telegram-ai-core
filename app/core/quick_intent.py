"""Быстрый маршрут текстовых фраз на crypto/portfolio без смены active_skill."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.agent_modes import AGENT_MODE_AGENT


@dataclass(frozen=True, slots=True)
class QuickIntent:
    """Результат классификации."""

    kind: str  # "none" | "portfolio" | "crypto_market"
    matched: bool = False


_PORTFOLIO_PATTERNS = (
    re.compile(r"\bсколько\s+у\s+меня\s+eth\b", re.IGNORECASE),
    re.compile(r"\bсколько\s+эфир", re.IGNORECASE),
    re.compile(r"\bмой\s+портфел", re.IGNORECASE),
    re.compile(r"\bмо(й|ё)\s+eth\b", re.IGNORECASE),
)

_CRYPTO_MARKET_PATTERNS = (
    re.compile(r"\bчто\s+по\s+рынку\b", re.IGNORECASE),
    re.compile(r"\bчто\s+с\s+eth\b", re.IGNORECASE),
    re.compile(r"\bкак\s+eth\b", re.IGNORECASE),
)


def classify_quick_intent(
    text: str,
    *,
    active_mode: str,
) -> QuickIntent:
    """Не меняет БД; только подсказка для routing.

    В режиме спецагента quick intent отключён, чтобы не ломать явный выбор пользователя.
    """
    raw = (text or "").strip()
    if not raw or raw.startswith("/"):
        return QuickIntent(kind="none", matched=False)
    if active_mode == AGENT_MODE_AGENT:
        return QuickIntent(kind="none", matched=False)

    lower = raw.lower()
    for rx in _PORTFOLIO_PATTERNS:
        if rx.search(lower):
            return QuickIntent(kind="portfolio", matched=True)
    for rx in _CRYPTO_MARKET_PATTERNS:
        if rx.search(lower):
            return QuickIntent(kind="crypto_market", matched=True)
    return QuickIntent(kind="none", matched=False)


__all__ = ["QuickIntent", "classify_quick_intent"]
