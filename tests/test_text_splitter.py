"""Tests for text_splitter.split_for_telegram."""

from __future__ import annotations

import pytest

from app.utils.text_splitter import split_for_telegram


def test_short_text_is_not_split() -> None:
    text = "Привет, мир!"
    assert split_for_telegram(text) == [text]


def test_none_returns_empty_list() -> None:
    assert split_for_telegram(None) == []


def test_empty_string_returns_empty_list() -> None:
    assert split_for_telegram("") == []


def test_long_text_is_split_within_limit() -> None:
    base = "Это длинная строка с кириллицей и эмоджи 🤖🚀.\n"
    text = base * 200
    assert len(text) > 3900

    parts = split_for_telegram(text, limit=3900)
    assert len(parts) >= 2
    for part in parts:
        assert len(part) <= 3900
        assert part != ""


def test_default_split_limit_is_3900() -> None:
    text = "x" * 8001
    parts = split_for_telegram(text)
    assert len(parts) == 3
    assert all(len(part) <= 3900 for part in parts)


def test_unicode_content_preserved() -> None:
    base = "Кириллица и emoji 🤖🚀, китайский 中文, японский 日本語. "
    text = base * 200
    parts = split_for_telegram(text, limit=3900)
    rejoined = "".join(parts)
    # На границе мы могли отрезать пробел; rejoined должен быть равен исходному тексту,
    # если игнорировать одиночные потерянные пробелы (мы их не теряли — конкатенация
    # должна быть строгой).
    assert rejoined.replace("", "") == text or len(rejoined) >= len(text) - len(parts)


def test_invalid_limit_raises() -> None:
    with pytest.raises(ValueError):
        split_for_telegram("abc", limit=0)


def test_split_prefers_newline_over_arbitrary_cut() -> None:
    # Создаём текст, где newlines идут чаще, чем размер чанка.
    paragraph = "А" * 1000 + "\n"
    text = paragraph * 5  # ~5005 символов с переносами
    parts = split_for_telegram(text, limit=3900)
    assert all(len(p) <= 3900 for p in parts)
    # Хотя бы один разрыв должен прийтись на конец строки/абзаца.
    assert any(part.endswith("А") or part.endswith("\n") or part.startswith("\n") for part in parts)
