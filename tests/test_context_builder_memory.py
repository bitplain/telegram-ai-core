"""Context builder injects memory lines into system prompt."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.agents.registry import get_agent_registry
from app.core.context_builder import ContextBuilder


class _FakeMemRepo:
    def __init__(self) -> None:
        self.called = False

    async def list_for_llm(self, *, user_id: uuid.UUID, agent_id: str):
        self.called = True
        return [
            SimpleNamespace(
                id=uuid.uuid4(),
                scope="global",
                agent_id=None,
                content="User likes Python",
            )
        ]


@pytest.mark.asyncio
async def test_build_messages_includes_memories_in_system(monkeypatch) -> None:
    import app.core.context_builder as module

    mem_repo = _FakeMemRepo()
    monkeypatch.setattr(module, "MemoryRepository", lambda session: mem_repo)

    class _FakeMsgRepo:
        async def list_recent_for_agent(self, **kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr(module, "MessageRepository", lambda session: _FakeMsgRepo())

    uid = uuid.uuid4()
    builder = ContextBuilder(session=None)  # type: ignore[arg-type]
    agent = get_agent_registry().get("crypto")
    conv = SimpleNamespace(id=uuid.uuid4(), active_agent_id="crypto")

    messages = await builder.build_messages(
        conversation=conv,  # type: ignore[arg-type]
        agent=agent,
        history_agent_id="crypto",
        user_id=uid,
    )
    assert mem_repo.called
    assert messages[0]["role"] == "system"
    assert "User likes Python" in messages[0]["content"]
    assert "User memories" in messages[0]["content"]
