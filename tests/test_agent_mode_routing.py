"""Тесты runtime routing для default/agent/one-shot режимов."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.agent_modes import (
    AGENT_MODE_AGENT,
    AGENT_MODE_DEFAULT,
    DEFAULT_AGENT_ID,
    DEFAULT_MODEL_ID,
    DEFAULT_SKILL_ID,
    resolve_runtime_context,
)


def _conversation(
    *,
    active_mode: str = AGENT_MODE_DEFAULT,
    active_agent_id: str = DEFAULT_AGENT_ID,
    active_skill_id: str = DEFAULT_SKILL_ID,
    active_model_id: str = DEFAULT_MODEL_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        active_mode=active_mode,
        active_agent_id=active_agent_id,
        active_skill_id=active_skill_id,
        active_model_id=active_model_id,
    )


def test_default_mode_uses_skill_router_keyword_matching() -> None:
    ctx = resolve_runtime_context(
        conversation=_conversation(),
        message_text="Расскажи про ethereum и комиссии",
    )

    assert ctx.active_mode == AGENT_MODE_DEFAULT
    assert ctx.agent_id == "crypto"
    assert ctx.skill_id == "crypto"
    assert ctx.model_id == "crypto_model"
    assert ctx.matched_by == "keyword"
    assert ctx.is_one_shot is False
    assert ctx.conversation_patch == {}


def test_agent_mode_uses_active_agent_without_keyword_override() -> None:
    ctx = resolve_runtime_context(
        conversation=_conversation(
            active_mode=AGENT_MODE_AGENT,
            active_agent_id="news",
            active_skill_id="news",
            active_model_id="news_model",
        ),
        message_text="Что думаешь про bitcoin?",
    )

    assert ctx.active_mode == AGENT_MODE_AGENT
    assert ctx.agent_id == "news"
    assert ctx.skill_id == "news"
    assert ctx.model_id == "news_model"
    assert ctx.matched_by == "agent_mode"
    assert ctx.conversation_patch == {}


def test_agent_mode_unknown_agent_falls_back_to_default_state() -> None:
    ctx = resolve_runtime_context(
        conversation=_conversation(
            active_mode=AGENT_MODE_AGENT,
            active_agent_id="missing",
            active_skill_id="news",
            active_model_id="news_model",
        ),
        message_text="Привет",
    )

    assert ctx.active_mode == AGENT_MODE_DEFAULT
    assert ctx.agent_id == "general"
    assert ctx.skill_id == "chat"
    assert ctx.model_id == "default_balanced"
    assert ctx.matched_by == "fallback_unknown_agent"
    assert ctx.conversation_patch == {
        "active_mode": "default",
        "agent_id": "general",
        "skill_id": "chat",
        "model_id": "default_balanced",
    }


def test_agent_mode_forbidden_active_model_falls_back_to_agent_default() -> None:
    ctx = resolve_runtime_context(
        conversation=_conversation(
            active_mode=AGENT_MODE_AGENT,
            active_agent_id="crypto",
            active_skill_id="crypto",
            active_model_id="devops_model",
        ),
        message_text="Разбери ETH",
    )

    assert ctx.agent_id == "crypto"
    assert ctx.model_id == "crypto_model"
    assert ctx.conversation_patch == {"model_id": "crypto_model"}


def test_one_shot_crypto_uses_agent_without_changing_conversation() -> None:
    conversation = _conversation(
        active_mode=AGENT_MODE_AGENT,
        active_agent_id="news",
        active_skill_id="news",
        active_model_id="news_model",
    )

    ctx = resolve_runtime_context(
        conversation=conversation,
        message_text="Что думаешь про BTC?",
        one_shot_agent_id="crypto",
    )

    assert ctx.active_mode == AGENT_MODE_AGENT
    assert ctx.agent_id == "crypto"
    assert ctx.skill_id == "crypto"
    assert ctx.model_id == "crypto_model"
    assert ctx.is_one_shot is True
    assert ctx.matched_by == "one_shot_agent"
    assert ctx.conversation_patch == {}
    assert conversation.active_agent_id == "news"

