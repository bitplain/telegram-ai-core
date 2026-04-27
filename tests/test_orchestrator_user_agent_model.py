from __future__ import annotations

import pytest

from app.agents.registry import get_agent_registry
from app.core.services.user_agent_settings import (
    AgentSettingsService,
    EffectiveAgentSettings,
)
from app.models.registry import get_model_registry


class _FakeSettingsService:
    async def get_effective_settings(
        self, *, telegram_user_id: int, agent_id: str
    ) -> EffectiveAgentSettings:
        agent = get_agent_registry().get(agent_id)
        model = get_model_registry().get("crypto_model")
        return EffectiveAgentSettings(
            agent=agent,
            default_prompt=agent.system_prompt,
            custom_prompt=None,
            effective_prompt=agent.system_prompt,
            default_model=get_model_registry().get(agent.default_model_id),
            selected_model=model,
            effective_model=model,
            custom_prompt_used=False,
        )


@pytest.mark.asyncio
async def test_orchestrator_applies_user_agent_model_override(monkeypatch) -> None:
    import app.core.orchestrator as module

    from app.core.orchestrator import Orchestrator

    class _NoDbSettingsStore:
        async def get_model_override(self, model_id: str) -> None:
            return None

    monkeypatch.setattr(module, "get_settings_store", lambda: _NoDbSettingsStore())

    agent = get_agent_registry().get("general")
    skill = type("Skill", (), {"model_id": None, "temperature": None})()
    orchestrator = Orchestrator(agent_settings_service=_FakeSettingsService())  # type: ignore[arg-type]

    plan = await orchestrator.plan_async(
        agent=agent,
        skill=skill,  # type: ignore[arg-type]
        telegram_user_id=123,
    )

    assert plan.model.id == "crypto_model"
