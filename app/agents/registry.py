"""Registry агентов."""

from __future__ import annotations

import logging

from app.agents.profiles.crypto import CRYPTO_AGENT
from app.agents.profiles.devops import DEVOPS_AGENT
from app.agents.profiles.finance import FINANCE_AGENT
from app.agents.profiles.general import GENERAL_AGENT
from app.agents.profiles.news import NEWS_AGENT
from app.agents.schemas import AgentProfile

log = logging.getLogger(__name__)


ALL_AGENTS: list[AgentProfile] = [
    GENERAL_AGENT,
    CRYPTO_AGENT,
    FINANCE_AGENT,
    NEWS_AGENT,
    DEVOPS_AGENT,
]


DEFAULT_AGENT_ID = GENERAL_AGENT.id


class AgentRegistry:
    """In-memory registry агентов."""

    def __init__(self, profiles: list[AgentProfile] | None = None) -> None:
        items = profiles if profiles is not None else ALL_AGENTS
        self._items: dict[str, AgentProfile] = {p.id: p for p in items}
        self._default_id = DEFAULT_AGENT_ID

    def get(self, agent_id: str | None) -> AgentProfile:
        """Возвращает агента по id. Неизвестный id → general + warning."""
        if agent_id and agent_id in self._items:
            return self._items[agent_id]
        if agent_id:
            log.warning(
                "Unknown agent_id '%s' — falling back to default '%s'",
                agent_id,
                self._default_id,
            )
        return self._items[self._default_id]

    def get_or_none(self, agent_id: str) -> AgentProfile | None:
        return self._items.get(agent_id)

    def list_enabled(self) -> list[AgentProfile]:
        return [p for p in self._items.values() if p.enabled]

    def list_all(self) -> list[AgentProfile]:
        return list(self._items.values())

    @property
    def default_id(self) -> str:
        return self._default_id


_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    return _registry


__all__ = [
    "AgentRegistry",
    "get_agent_registry",
    "ALL_AGENTS",
    "DEFAULT_AGENT_ID",
]
