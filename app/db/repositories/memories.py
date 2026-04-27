"""Repository for user memories (MVP)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MEMORY_SCOPE_AGENT, MEMORY_SCOPE_GLOBAL, Memory


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_memory(
        self,
        *,
        user_id: uuid.UUID,
        content: str,
        scope: str,
        agent_id: str | None = None,
    ) -> Memory:
        row = Memory(
            user_id=user_id,
            content=content.strip(),
            scope=scope,
            agent_id=agent_id if scope == MEMORY_SCOPE_AGENT else None,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_global_memories(self, *, user_id: uuid.UUID) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id, Memory.scope == MEMORY_SCOPE_GLOBAL)
            .order_by(Memory.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_agent_memories(
        self, *, user_id: uuid.UUID, agent_id: str
    ) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.scope == MEMORY_SCOPE_AGENT,
                Memory.agent_id == agent_id,
            )
            .order_by(Memory.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_owned(self, *, memory_id: uuid.UUID, user_id: uuid.UUID) -> Memory | None:
        stmt = select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete_memory(self, *, memory_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0


def memory_context_block(
    *,
    global_memories: list[Memory],
    agent_memories: list[Memory],
) -> str:
    """Short block for LLM system context."""
    parts: list[str] = []
    if global_memories:
        lines = [f"- [{m.id}] {m.content}" for m in global_memories]
        parts.append("User global memories:\n" + "\n".join(lines))
    if agent_memories:
        lines = [f"- [{m.id}] {m.content}" for m in agent_memories]
        parts.append("User memories for this agent:\n" + "\n".join(lines))
    if not parts:
        return ""
    return "\n\n".join(parts)


__all__ = [
    "MemoryRepository",
    "memory_context_block",
]
