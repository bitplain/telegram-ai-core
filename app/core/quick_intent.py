"""Мгновенные намерения без смены режима диалога (портфель / рынок)."""

from __future__ import annotations

import re
from enum import Enum


class QuickIntent(str, Enum):
    PORTFOLIO = "portfolio"
    CRYPTO_MARKET = "crypto_market"


_PORTFOLIO_RE = re.compile(
    r"(сколько\s+у\s+меня\s+(eth|ethereum|эфир|эфира|эфире))"
    r"|((eth|ethereum|эфир|эфира)\s+у\s+меня)"
    r"|(мой\s+(портфель|баланс))"
    r"|(портфель|баланс).{0,40}(eth|ethereum|эфир)"
    r"|(сколько\s+(eth|ethereum|эфир))",
    re.IGNORECASE | re.DOTALL,
)

_MARKET_RE = re.compile(
    r"(что\s+по\s+рынку)"
    r"|(как\s+рынок)"
    r"|(ситуаци\w+\s+на\s+рынке)"
    r"|(обзор\s+рынка)"
    r"|(крипторынок)",
    re.IGNORECASE,
)


def detect_quick_intent(text: str) -> QuickIntent | None:
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if _PORTFOLIO_RE.search(low):
        return QuickIntent.PORTFOLIO
    if _MARKET_RE.search(low):
        return QuickIntent.CRYPTO_MARKET
    return None
