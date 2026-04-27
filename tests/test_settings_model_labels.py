"""Тесты подписей моделей в admin /settings."""

from __future__ import annotations

from app.bot.handlers.settings import _agent_models_keyboard
def test_agent_model_buttons_use_favorite_openrouter_model_names() -> None:
    favorites = ["openai/gpt-4.1-mini", "google/gemini-2.0-flash-001"]
    keyboard = _agent_models_keyboard("general", favorites)
    button_texts = [row[0].text for row in keyboard.inline_keyboard[:-1]]

    assert button_texts == favorites
    assert "default_fast" not in button_texts
    assert "default_balanced" not in button_texts
