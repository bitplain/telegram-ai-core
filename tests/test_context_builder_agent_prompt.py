"""Тесты применения user-scoped system prompt при сборке LLM-контекста."""

from __future__ import annotations

from app.agents.registry import get_agent_registry
from app.core.context_builder import ContextBuilder


class _FakeMessageRepo:
    def __init__(self) -> None:
        self.list_recent_calls = []
        self.list_recent_for_agent_calls = []

    async def list_recent(self, *, conversation_id, limit: int, agent_id=None):  # noqa: ANN001
        self.list_recent_calls.append(
            {"conversation_id": conversation_id, "limit": limit, "agent_id": agent_id}
        )
        return []

    async def list_recent_for_agent(  # noqa: ANN001
        self,
        *,
        conversation_id,
        agent_id: str,
        limit: int,
    ):
        self.list_recent_for_agent_calls.append(
            {"conversation_id": conversation_id, "agent_id": agent_id, "limit": limit}
        )
        return []


class _FakeConversation:
    id = "conv-1"


async def test_context_builder_uses_custom_system_prompt(monkeypatch) -> None:
    import app.core.context_builder as module

    repo = _FakeMessageRepo()
    monkeypatch.setattr(module, "MessageRepository", lambda session: repo)
    builder = ContextBuilder(session=None)  # type: ignore[arg-type]
    agent = get_agent_registry().get("crypto")

    messages = await builder.build_messages(
        conversation=_FakeConversation(),  # type: ignore[arg-type]
        agent=agent,
        system_prompt_override="Пользовательский prompt",
    )

    assert messages[0] == {"role": "system", "content": "Пользовательский prompt"}


async def test_context_builder_uses_explicit_agent_scoped_history(monkeypatch) -> None:
    import app.core.context_builder as module

    repo = _FakeMessageRepo()
    monkeypatch.setattr(module, "MessageRepository", lambda session: repo)
    builder = ContextBuilder(session=None)  # type: ignore[arg-type]
    agent = get_agent_registry().get("crypto")

    await builder.build_messages(
        conversation=_FakeConversation(),  # type: ignore[arg-type]
        agent=agent,
        history_agent_id="crypto",
    )

    assert repo.list_recent_calls == []
    assert repo.list_recent_for_agent_calls == [
        {"conversation_id": "conv-1", "agent_id": "crypto", "limit": 20}
    ]


async def test_context_builder_appends_memory_suffix(monkeypatch) -> None:
    import app.core.context_builder as module

    repo = _FakeMessageRepo()
    monkeypatch.setattr(module, "MessageRepository", lambda session: repo)
    builder = ContextBuilder(session=None)  # type: ignore[arg-type]
    agent = get_agent_registry().get("crypto")

    messages = await builder.build_messages(
        conversation=_FakeConversation(),  # type: ignore[arg-type]
        agent=agent,
        system_prompt_override="Base",
        memory_system_append="\n\n---\nMemory: test fact",
    )

    assert messages[0]["role"] == "system"
    assert "Base" in messages[0]["content"]
    assert "test fact" in messages[0]["content"]
