"""Tests for agents registry."""

from __future__ import annotations

from app.agents.registry import get_agent_registry


def test_default_agent_is_general() -> None:
    registry = get_agent_registry()
    assert registry.default_id == "general"


def test_get_general() -> None:
    registry = get_agent_registry()
    agent = registry.get("general")
    assert agent.id == "general"
    assert agent.name


def test_get_crypto() -> None:
    registry = get_agent_registry()
    agent = registry.get("crypto")
    assert agent.id == "crypto"


def test_unknown_falls_back_to_general() -> None:
    registry = get_agent_registry()
    agent = registry.get("does-not-exist")
    assert agent.id == "general"


def test_all_enabled_have_required_fields() -> None:
    registry = get_agent_registry()
    for agent in registry.list_enabled():
        assert agent.id
        assert agent.name
        assert agent.system_prompt
        assert 0.0 <= agent.temperature <= 2.0
        assert agent.max_context_messages > 0


def test_enabled_set_includes_default() -> None:
    registry = get_agent_registry()
    enabled_ids = {a.id for a in registry.list_enabled()}
    assert "general" in enabled_ids


def test_allowed_models_are_consistent() -> None:
    registry = get_agent_registry()
    for agent in registry.list_enabled():
        if agent.allowed_model_ids:
            assert agent.default_model_id in agent.allowed_model_ids


def test_allowed_tools_is_empty_on_mvp() -> None:
    registry = get_agent_registry()
    for agent in registry.list_enabled():
        # На MVP tools архитектурно есть, но пустые.
        assert isinstance(agent.allowed_tools, list)
        assert agent.allowed_tools == []
