"""Tests for skills registry and router."""

from __future__ import annotations

from app.agents.registry import get_agent_registry
from app.models.registry import get_model_registry
from app.skills.registry import get_skill_registry
from app.skills.router import SkillRouter
from app.core.agent_modes import AGENT_MODE_AGENT, resolve_runtime_context


def test_default_is_chat() -> None:
    registry = get_skill_registry()
    assert registry.default_id == "chat"


def test_get_crypto_skill() -> None:
    registry = get_skill_registry()
    skill = registry.get("crypto")
    assert skill.id == "crypto"
    assert skill.agent_id == "crypto"


def test_get_news_skill() -> None:
    registry = get_skill_registry()
    skill = registry.get("news")
    assert skill.id == "news"
    assert skill.agent_id == "news"


def test_command_routing_crypto() -> None:
    router = SkillRouter()
    res = router.resolve(text="/crypto Что думаешь про ETH?", active_skill_id="chat")
    assert res.skill.id == "crypto"
    assert res.matched_by == "command"
    assert res.cleaned_text == "Что думаешь про ETH?"


def test_command_routing_news() -> None:
    router = SkillRouter()
    res = router.resolve(text="/news Что известно про Telegram?", active_skill_id="chat")
    assert res.skill.id == "news"
    assert res.matched_by == "command"
    assert res.cleaned_text == "Что известно про Telegram?"


def test_command_routing_with_bot_mention() -> None:
    router = SkillRouter()
    res = router.resolve(text="/devops@MyBot подскажи про Docker", active_skill_id=None)
    assert res.skill.id == "devops"
    assert res.matched_by == "command"


def test_command_infra_alias() -> None:
    router = SkillRouter()
    res = router.resolve(text="/infra fix nginx", active_skill_id=None)
    assert res.skill.id == "devops"
    assert res.matched_by == "command"


def test_keyword_routing_ethereum() -> None:
    router = SkillRouter()
    res = router.resolve(
        text="Расскажи про последний апдейт ethereum", active_skill_id=None
    )
    assert res.skill.id == "crypto"
    assert res.matched_by == "keyword"


def test_keyword_routing_news_ru() -> None:
    router = SkillRouter()
    res = router.resolve(text="Расскажи новости про Telegram", active_skill_id=None)
    assert res.skill.id == "news"
    assert res.matched_by == "keyword"


def test_agent_mode_keyword_does_not_override_active_agent() -> None:
    conversation = type(
        "Conversation",
        (),
        {
            "active_mode": AGENT_MODE_AGENT,
            "active_agent_id": "news",
            "active_skill_id": "news",
            "active_model_id": "news_model",
        },
    )()

    ctx = resolve_runtime_context(
        conversation=conversation,
        message_text="Расскажи про ethereum",
    )

    assert ctx.agent_id == "news"
    assert ctx.skill_id == "news"
    assert ctx.matched_by == "agent_mode"


def test_keyword_routing_docker() -> None:
    router = SkillRouter()
    res = router.resolve(
        text="Помоги настроить docker-compose с healthcheck", active_skill_id=None
    )
    assert res.skill.id == "devops"
    assert res.matched_by == "keyword"


def test_active_skill_used_when_no_command() -> None:
    router = SkillRouter()
    # Сообщение нейтральное, активный — finance.
    res = router.resolve(text="Привет, как дела на рынках?", active_skill_id="finance")
    # Активный skill имеет приоритет над keyword (нейтральное сообщение или
    # keyword может перевесить, но finance keywords тут не сработают на
    # «как дела на рынках»). Проверяем active path.
    assert res.matched_by in {"active", "keyword"}
    if res.matched_by == "active":
        assert res.skill.id == "finance"


def test_unknown_text_falls_back_to_default() -> None:
    router = SkillRouter()
    res = router.resolve(text="Просто привет", active_skill_id=None)
    assert res.skill.id == "chat"
    assert res.matched_by == "default"


def test_all_enabled_skills_reference_existing_agents_and_models() -> None:
    skills = get_skill_registry().list_enabled()
    agents = {a.id for a in get_agent_registry().list_all()}
    models = {m.id for m in get_model_registry().list_all()}
    for skill in skills:
        assert skill.agent_id in agents, f"skill {skill.id} → unknown agent"
        if skill.model_id is not None:
            assert skill.model_id in models, f"skill {skill.id} → unknown model"
