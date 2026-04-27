"""Ранний фильтр: блокирует чувствительный контент до любой записи в БД."""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

# BIP-39: 12/15/18/21/24 слов из фиксированного словаря; проверяем 12+ подряд латиницей
_MNEMO_WORD = r"[a-z]+"
# Разделяем повторяющимся разделителем (один+ пробел/перенос/таб)
_MNEMO_RUN = re.compile(
    rf"(?:{_MNEMO_WORD}(?:\s+{_MNEMO_WORD}){{11,}})", re.IGNORECASE
)

# 0x + 64 hex
_ETH_KEY = re.compile(r"0x[a-fA-F0-9]{64}\b")
# 64 hex без 0x (как вставка ключа)
_HEX64 = re.compile(r"(?<![0-9a-fA-F])([a-fA-F0-9]{64})(?![0-9a-fA-F])")

# Подсказки пользователю (низкий риск ложнопозитивов на коротких фразах)
_KEYWORD_PATTERNS: list[tuple[Pattern[str], str]] = [
    (re.compile(r"приватн(ый|ого)\s+ключ", re.IGNORECASE), "private_key_ru"),
    (re.compile(r"сид[- ]?фраз", re.IGNORECASE), "seed_phrase_ru"),
    (re.compile(r"мнемоник", re.IGNORECASE), "mnemonic_ru"),
    (re.compile(r"seed\s+phrase", re.IGNORECASE), "seed_phrase_en"),
    (re.compile(r"private\s+key", re.IGNORECASE), "private_key_en"),
    (re.compile(r"\bmnemonic\b", re.IGNORECASE), "mnemonic_en"),
]

BLOCK_MESSAGE = (
    "Сообщение не обработано: похоже, в нём есть приватный ключ или сид-фраза. "
    "Не отправляй секреты в чат. При утечке смени ключи или кошелёк в безопасной среде."
)


@dataclass(frozen=True, slots=True)
class SensitiveBlockResult:
    blocked: bool
    reason: str | None  # внутренняя метка для логов, без user-текста


def detect_sensitive_user_text(text: str) -> SensitiveBlockResult:
    """Возвращает blocked=True, если нельзя обрабатывать сообщение дальше.

    Не логирует и не хранит ``text`` — только возвращает факт и короткую причину.
    """
    if not text or not text.strip():
        return SensitiveBlockResult(blocked=False, reason=None)

    s = text.strip()

    for pat, reason in _KEYWORD_PATTERNS:
        if pat.search(s):
            return SensitiveBlockResult(blocked=True, reason=reason)

    if _ETH_KEY.search(s) or _HEX64.search(s):
        return SensitiveBlockResult(blocked=True, reason="hex_private_key")

    for m in _MNEMO_RUN.finditer(s):
        words = m.group(0).lower().split()
        if len(words) >= 12:
            return SensitiveBlockResult(blocked=True, reason="mnemonic_phrase")

    return SensitiveBlockResult(blocked=False, reason=None)


__all__ = [
    "BLOCK_MESSAGE",
    "SensitiveBlockResult",
    "detect_sensitive_user_text",
]
