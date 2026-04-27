"""Тесты подписей моделей в admin /settings."""

from __future__ import annotations

from app.bot.handlers.settings import _agent_models_keyboard
from app.models.registry import get_model_registry


def test_agent_model_buttons_use_openrouter_model_names() -> None:
    keyboard = _agent_models_keyboard("general")
    button_texts = [row[0].text for row in keyboard.inline_keyboard[:-1]]
    models = get_model_registry().list_enabled()

    assert button_texts == [model.model_name for model in models]
    assert "default_fast" not in button_texts
    assert "default_balanced" not in button_texts
