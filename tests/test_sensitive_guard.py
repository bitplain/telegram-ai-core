"""Sensitive input guard heuristics."""

from __future__ import annotations

import pytest

from app.core.security.sensitive_input_guard import is_sensitive_user_text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("hello world", False),
        ("here is my private key", True),
        ("сид фраза из 12 слов", True),
        ("мнемоника для кошелька", True),
        (
            "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
            True,
        ),
        ("0x" + "a" * 64, True),
    ],
)
def test_is_sensitive_user_text(text: str, expected: bool) -> None:
    assert is_sensitive_user_text(text) is expected
