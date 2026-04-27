"""Тесты режима специализированных агентов."""

from __future__ import annotations

from types import SimpleNamespace

from app.agents.registry import get_agent_registry
from app.core.agent_modes import (
    AGENT_MODE_AGENT,
    AGENT_MODE_DEFAULT,
    build_agent_mode_activation,
    build_default_mode_activation,
    resolve_message_route,
)


def test_agent_menu_candidates_do_not_include_general() -> None:
    registry = get_agent_registry()

    ids = [agent.id for agent in registry.list_agent_menu_enabled()]

    assert "general" not in ids
    assert ids == ["crypto", "news"]


def test_agent_menu_keyboard_does_not_show_general() -> None:
    from app.bot.handlers.commands import _agent_menu_keyboard

    keyboard = _agent_menu_keyboard(show_exit=False)
    button_text = [button.text for row in keyboard.inline_keyboard for button in row]

    assert "Универсальный ассистент" not in button_text
    assert "Криптовалютный аналитик" in button_text
    assert "Новостной агент" in button_text


def test_agent_callbacks_are_registered_once() -> None:
    from app.bot.handlers import commands

    assert commands.cb_agent_settings.__module__ == "app.bot.handlers.commands"


def test_settings_callback_bridge_is_importable() -> None:
    from app.bot.handlers.settings import render_agents_settings_callback

    assert callable(render_agents_settings_callback)


def test_crypto_activation_enables_agent_mode() -> None:
    activation = build_agent_mode_activation("crypto")

    assert activation.active_mode == AGENT_MODE_AGENT
    assert activation.active_agent_id == "crypto"
    assert activation.active_skill_id == "crypto"
    assert activation.active_model_id == "crypto_model"
    assert activation.agent.name == "Криптовалютный аналитик"


def test_news_activation_enables_agent_mode() -> None:
    activation = build_agent_mode_activation("news")

    assert activation.active_mode == AGENT_MODE_AGENT
    assert activation.active_agent_id == "news"
    assert activation.active_skill_id == "news"
    assert activation.active_model_id == "news_model"
    assert activation.agent.name == "Новостной агент"


def test_exit_activation_returns_to_default_general() -> None:
    activation = build_default_mode_activation()

    assert activation.active_mode == AGENT_MODE_DEFAULT
    assert activation.active_agent_id == "general"
    assert activation.active_skill_id == "chat"
    assert activation.active_model_id == "default_balanced"


def test_agent_mode_routes_by_active_agent_without_keyword_routing() -> None:
    conversation = SimpleNamespace(
        active_mode=AGENT_MODE_AGENT,
        active_agent_id="news",
        active_skill_id="news",
        active_model_id="news_model",
    )

    route = resolve_message_route(
        text="Что думаешь про bitcoin и ethereum?",
        conversation=conversation,
    )

    assert route.agent.id == "news"
    assert route.skill.id == "news"
    assert route.model_id == "news_model"
    assert route.matched_by == "agent_mode"
    assert route.cleaned_text == "Что думаешь про bitcoin и ethereum?"


def test_agent_mode_falls_back_to_agent_default_model_when_model_forbidden() -> None:
    conversation = SimpleNamespace(
        active_mode=AGENT_MODE_AGENT,
        active_agent_id="crypto",
        active_skill_id="crypto",
        active_model_id="devops_model",
    )

    route = resolve_message_route(text="Разбери ETH", conversation=conversation)

    assert route.agent.id == "crypto"
    assert route.skill.id == "crypto"
    assert route.model_id == "crypto_model"


def test_default_mode_uses_skill_router_keyword_matching() -> None:
    conversation = SimpleNamespace(
        active_mode=AGENT_MODE_DEFAULT,
        active_agent_id="general",
        active_skill_id=None,
        active_model_id="default_balanced",
    )

    route = resolve_message_route(
        text="Расскажи про bitcoin",
        conversation=conversation,
    )

    assert route.agent.id == "crypto"
    assert route.skill.id == "crypto"
    assert route.model_id == "crypto_model"
    assert route.matched_by == "keyword"
