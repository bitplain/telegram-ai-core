"""Heuristic guard against seed phrases, mnemonics and private keys in user text."""

from __future__ import annotations

import re

# User-facing copy (also used by handlers).
SENSITIVE_INPUT_BLOCKED_MESSAGE = (
    "Нельзя отправлять или сохранять seed-фразы, mnemonic или приватные ключи. "
    "Я не сохранил это сообщение."
)

# English phrases (substring match, case-insensitive).
_PHRASE_EN = (
    "seed phrase",
    "seed-phrases",
    "mnemonic",
    "private key",
    "recovery phrase",
    "secret phrase",
)

# Russian phrases / words.
_PHRASE_RU = (
    "сид фраза",
    "сид-фраза",
    "seed-фраза",
    "сидфраза",
    "приватный ключ",
    "мнемоника",
    "мнемоническая фраза",
    "секретная фраза",
    "фраза восстановления",
)

# Ethereum / hex private keys (64 hex chars, optional 0x).
_HEX_PRIV_64 = re.compile(r"\b0x[a-fA-F0-9]{64}\b")
_HEX_PRIV_64_NAKED = re.compile(r"(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])")

# Base58-ish WIF often starts with 5, K, L for Bitcoin — high false positive if alone;
# combine with phrase hints only. Detect 51-52 char base58 if line looks like a key.
_WIF_LIKE = re.compile(r"\b[5KL][1-9A-HJ-NP-Za-km-z]{50,51}\b")


def _normalize_for_scan(text: str) -> str:
    return text.strip()


def _has_phrase_hint(text: str) -> bool:
    lower = text.lower()
    for p in _PHRASE_EN:
        if p in lower:
            return True
    lower_ru = lower
    for p in _PHRASE_RU:
        if p in lower_ru:
            return True
    return False


def _looks_like_mnemonic_sentence(text: str) -> bool:
    """12+ or 24+ lowercase letter-only words 3–8 chars (typical typed mnemonic)."""
    word_re = re.compile(r"^[a-z]{3,8}$")
    for line in text.splitlines():
        words = line.strip().split()
        if len(words) < 12:
            continue
        for need in (24, 12):
            if len(words) < need:
                continue
            for i in range(len(words) - need + 1):
                chunk = words[i : i + need]
                if all(word_re.match(w) for w in chunk):
                    return True
    return False


def _looks_like_hex_private_key(text: str) -> bool:
    if _HEX_PRIV_64.search(text):
        return True
    # Naked 64 hex: avoid matching long hashes — require word boundaries via lookaround.
    for m in _HEX_PRIV_64_NAKED.finditer(text):
        chunk = m.group(0)
        # All hex and length 64
        if len(chunk) == 64 and re.fullmatch(r"[a-fA-F0-9]+", chunk):
            return True
    return False


def _looks_like_wif_with_context(text: str) -> bool:
    if not _has_phrase_hint(text):
        return False
    return bool(_WIF_LIKE.search(text))


def is_sensitive_user_text(text: str) -> bool:
    """Return True if the text must not be stored or sent to an LLM."""
    t = _normalize_for_scan(text)
    if not t:
        return False

    if _has_phrase_hint(t):
        return True

    if _looks_like_mnemonic_sentence(t):
        return True

    if _looks_like_hex_private_key(t):
        return True

    if _looks_like_wif_with_context(t):
        return True

    # "Private key" style: long base64url / base58 blob on one line without spaces.
    if re.search(r"\b[a-zA-Z0-9+/]{80,}={0,2}\b", t) and len(t) < 500:
        # High entropy line — only flag if also looks like key export.
        if "BEGIN" in t and "PRIVATE" in t.upper():
            return True

    if "BEGIN EC PRIVATE" in t.upper() or "BEGIN RSA PRIVATE" in t.upper():
        return True

    return False
