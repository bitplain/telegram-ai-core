"""Orchestrator must use OPENROUTER_API_KEY from settings (ENV), not SettingsStore."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents.registry import get_agent_registry
from app.llm.openrouter_client import StreamingChunk


@pytest.mark.asyncio
async def test_orchestrator_run_uses_openrouter_key_from_env_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod,
        "get_settings",
        lambda: MagicMock(OPENROUTER_API_KEY="sk-or-v1-testenvkey"),
    )

    agent = get_agent_registry().get("general")
    skill = type("Skill", (), {"model_id": None, "temperature": None})()

    captured: dict[str, str | None] = {}

    async def fake_stream(**kwargs):  # noqa: ANN003
        captured["api_key_override"] = kwargs.get("api_key_override")
        yield StreamingChunk(content_delta="ok", finish_reason="stop")

    client = MagicMock()
    client.stream_chat_completion = MagicMock(side_effect=fake_stream)

    orchestrator = orch_mod.Orchestrator(client=client)
    plan = orchestrator.plan(agent=agent, skill=skill)

    out = []
    async for chunk in orchestrator.run(plan=plan, messages=[{"role": "user", "content": "hi"}]):
        out.append(chunk)

    assert captured.get("api_key_override") == "sk-or-v1-testenvkey"
    assert len(out) == 1
