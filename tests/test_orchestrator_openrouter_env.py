"""Orchestrator uses OPENROUTER_API_KEY from ENV only."""

from __future__ import annotations

from typing import Any
import pytest

from app.agents.registry import get_agent_registry
from app.core.orchestrator import Orchestrator, OrchestratorPlan
from app.models.registry import get_model_registry
from app.skills.registry import get_skill_registry


@pytest.mark.asyncio
async def test_orchestrator_run_passes_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-testenvkey")
    from app.config import reload_settings

    reload_settings()

    captured: dict[str, Any] = {}

    class _FakeClient:
        async def stream_chat_completion(self, **kwargs: Any):
            captured["api_key_override"] = kwargs.get("api_key_override")
            yield type("C", (), {"content_delta": "x", "finish_reason": "stop"})()

    agent = get_agent_registry().get("general")
    skill = get_skill_registry().get("chat")
    model = get_model_registry().get(agent.default_model_id)
    plan = OrchestratorPlan(
        agent=agent,
        skill=skill,
        model=model,
        temperature=0.3,
        max_tokens=100,
    )
    orch = Orchestrator(client=_FakeClient())  # type: ignore[arg-type]
    chunks = [
        c.content_delta
        async for c in orch.run(
            plan=plan,
            messages=[{"role": "user", "content": "hi"}],
        )
    ]
    assert chunks == ["x"]
    assert captured["api_key_override"] == "sk-or-v1-testenvkey"
