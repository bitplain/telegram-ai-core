"""Тесты применения user-scoped system prompt при сборке LLM-контекста."""

from __future__ import annotations

from app.agents.registry import get_agent_registry
from app.core.context_builder import ContextBuilder


class _FakeMessageRepo:
    async def list_recent(self, *, conversation_id, limit: int, agent_id=None):  # noqa: ANN001
        return []


class _FakeConversation:
    id = "conv-1"


async def test_context_builder_uses_custom_system_prompt(monkeypatch) -> None:
    import app.core.context_builder as module

    monkeypatch.setattr(module, "MessageRepository", lambda session: _FakeMessageRepo())
    builder = ContextBuilder(session=None)  # type: ignore[arg-type]
    agent = get_agent_registry().get("crypto")

    messages = await builder.build_messages(
        conversation=_FakeConversation(),  # type: ignore[arg-type]
        agent=agent,
        system_prompt_override="Пользовательский prompt",
    )

    assert messages[0] == {"role": "system", "content": "Пользовательский prompt"}

