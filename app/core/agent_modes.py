"""Правила включения и маршрутизации режимов специализированных агентов."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agents.registry import AgentRegistry, get_agent_registry
from app.agents.schemas import AgentProfile
from app.models.registry import ModelRegistry, get_model_registry
from app.skills.registry import SkillRegistry, get_skill_registry
from app.skills.router import SkillRouter
from app.skills.schemas import SkillProfile

AGENT_MODE_DEFAULT = "default"
AGENT_MODE_AGENT = "agent"

DEFAULT_AGENT_ID = "general"
DEFAULT_SKILL_ID = "chat"
DEFAULT_MODEL_ID = "default_balanced"


class ConversationRoutingState(Protocol):
    active_mode: str
    active_agent_id: str
    active_skill_id: str
    active_model_id: str


@dataclass(frozen=True, slots=True)
class AgentModeActivation:
    active_mode: str
    active_agent_id: str
    active_skill_id: str
    active_model_id: str
    agent: AgentProfile
    skill: SkillProfile


@dataclass(frozen=True, slots=True)
class MessageRoute:
    agent: AgentProfile
    skill: SkillProfile
    model_id: str
    matched_by: str
    cleaned_text: str


def build_default_mode_activation(
    *,
    agent_registry: AgentRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
) -> AgentModeActivation:
    """Возвращает routing-состояние обычного режима."""
    agents = agent_registry or get_agent_registry()
    skills = skill_registry or get_skill_registry()
    agent = agents.get(DEFAULT_AGENT_ID)
    skill = skills.get(DEFAULT_SKILL_ID)
    return AgentModeActivation(
        active_mode=AGENT_MODE_DEFAULT,
        active_agent_id=agent.id,
        active_skill_id=skill.id,
        active_model_id=DEFAULT_MODEL_ID,
        agent=agent,
        skill=skill,
    )


def build_agent_mode_activation(
    agent_id: str,
    *,
    agent_registry: AgentRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
) -> AgentModeActivation:
    """Возвращает routing-состояние включённого спецагента."""
    agents = agent_registry or get_agent_registry()
    skills = skill_registry or get_skill_registry()
    agent = agents.get_or_none(agent_id)
    if agent is None or not agent.enabled or not agent.show_in_agent_menu:
        raise ValueError(agent_id)
    skill = _first_enabled_agent_skill(agent=agent, skill_registry=skills)
    return AgentModeActivation(
        active_mode=AGENT_MODE_AGENT,
        active_agent_id=agent.id,
        active_skill_id=skill.id,
        active_model_id=skill.model_id or agent.default_model_id,
        agent=agent,
        skill=skill,
    )


def resolve_message_route(
    *,
    text: str,
    conversation: ConversationRoutingState,
    agent_registry: AgentRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
    model_registry: ModelRegistry | None = None,
    skill_router: SkillRouter | None = None,
) -> MessageRoute:
    """Выбирает agent/skill/model для обычного текстового сообщения."""
    agents = agent_registry or get_agent_registry()
    skills = skill_registry or get_skill_registry()
    models = model_registry or get_model_registry()
    active_mode = getattr(conversation, "active_mode", AGENT_MODE_DEFAULT)

    if active_mode == AGENT_MODE_AGENT:
        agent = agents.get(getattr(conversation, "active_agent_id", None))
        skill = _first_enabled_agent_skill(agent=agent, skill_registry=skills)
        active_model_id = getattr(conversation, "active_model_id", None)
        model_id = _allowed_or_default_model_id(
            agent=agent,
            model_id=active_model_id,
            model_registry=models,
        )
        return MessageRoute(
            agent=agent,
            skill=skill,
            model_id=model_id,
            matched_by="agent_mode",
            cleaned_text=text,
        )

    active_skill_id = getattr(conversation, "active_skill_id", None)
    router_active_skill_id = None if active_skill_id == DEFAULT_SKILL_ID else active_skill_id
    router = skill_router or SkillRouter(registry=skills)
    resolution = router.resolve(text=text, active_skill_id=router_active_skill_id)
    skill = resolution.skill
    agent = agents.get(skill.agent_id)
    model_id = _allowed_or_default_model_id(
        agent=agent,
        model_id=skill.model_id or agent.default_model_id,
        model_registry=models,
    )
    return MessageRoute(
        agent=agent,
        skill=skill,
        model_id=model_id,
        matched_by=resolution.matched_by,
        cleaned_text=resolution.cleaned_text or text,
    )


def available_agent_mode_ids(agent_registry: AgentRegistry | None = None) -> list[str]:
    """Список id спецагентов, доступных через /agent."""
    registry = agent_registry or get_agent_registry()
    return [agent.id for agent in registry.list_agent_menu_enabled()]


def _first_enabled_agent_skill(
    *,
    agent: AgentProfile,
    skill_registry: SkillRegistry,
) -> SkillProfile:
    for skill_id in agent.skill_ids:
        skill = skill_registry.get_or_none(skill_id)
        if skill is not None and skill.enabled and skill.agent_id == agent.id:
            return skill
    return skill_registry.get(DEFAULT_SKILL_ID)


def _allowed_or_default_model_id(
    *,
    agent: AgentProfile,
    model_id: str | None,
    model_registry: ModelRegistry,
) -> str:
    candidate = model_id if model_id and model_registry.get_or_none(model_id) else None
    if candidate and (not agent.allowed_model_ids or candidate in agent.allowed_model_ids):
        return candidate
    return agent.default_model_id


__all__ = [
    "AGENT_MODE_AGENT",
    "AGENT_MODE_DEFAULT",
    "AgentModeActivation",
    "MessageRoute",
    "available_agent_mode_ids",
    "build_agent_mode_activation",
    "build_default_mode_activation",
    "resolve_message_route",
]
