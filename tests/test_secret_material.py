"""Tests for secret-material detection (wallet commands)."""

from __future__ import annotations

from app.utils.secret_material import looks_like_secret_material


def test_detects_eth_private_key_hex() -> None:
    assert looks_like_secret_material(
        "0x" + "a" * 64
    )


def test_detects_seed_keywords() -> None:
    assert looks_like_secret_material("here is my private key please help")


def test_normal_portfolio_command_not_flagged() -> None:
    assert not looks_like_secret_material("/portfolio_add_eth 0.25 3200 arbitrum")


def test_bip39_like_sequence() -> None:
    phrase = " ".join(
        [
            "abandon", "abandon", "abandon", "abandon", "abandon",
            "abandon", "abandon", "abandon", "abandon", "abandon",
            "abandon", "abandon",
        ]
    )
    assert looks_like_secret_material(phrase)
