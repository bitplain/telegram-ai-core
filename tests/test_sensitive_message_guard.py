"""Тесты детектора секретов в сообщениях."""

from __future__ import annotations

import pytest

from app.core.sensitive_message_guard import detect_sensitive_user_text


def test_mnemonic_like_sequence_detected() -> None:
    w = " ".join(["abandon"] * 12)
    r = detect_sensitive_user_text(f"сохрани {w}")
    assert r.blocked
    assert r.reason == "mnemonic_phrase"


def test_ethereum_key_hex() -> None:
    key = "0x" + "a" * 64
    r = detect_sensitive_user_text(f"вот {key} ключ")
    assert r.blocked
    assert r.reason == "hex_private_key"


def test_russian_keywords() -> None:
    assert detect_sensitive_user_text("вот сид-фраза кошелька").blocked
    assert detect_sensitive_user_text("мнемоника из 12").blocked
    assert detect_sensitive_user_text("мой приватный ключ 123").blocked


def test_harmless_text() -> None:
    r = detect_sensitive_user_text("привет как дела")
    assert not r.blocked
