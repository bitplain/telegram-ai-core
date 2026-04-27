"""Repository for user memories (global and per-agent)."""

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
            agent_id=agent_id if scope == MEMORY_SCOPE_AGENT else None,
            scope=scope,
            content=content.strip(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        agent_id_for_scope: str | None = None,
    ) -> tuple[list[Memory], list[Memory]]:
        """Returns (global_memories, agent_memories for agent_id)."""
        g_stmt = (
            select(Memory)
            .where(Memory.user_id == user_id, Memory.scope == MEMORY_SCOPE_GLOBAL)
            .order_by(Memory.created_at.asc())
        )
        g_rows = list((await self._session.execute(g_stmt)).scalars().all())

        a_rows: list[Memory] = []
        if agent_id_for_scope:
            a_stmt = (
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.scope == MEMORY_SCOPE_AGENT,
                    Memory.agent_id == agent_id_for_scope,
                )
                .order_by(Memory.created_at.asc())
            )
            a_rows = list((await self._session.execute(a_stmt)).scalars().all())
        return g_rows, a_rows

    async def list_for_llm(
        self, *, user_id: uuid.UUID, agent_id: str
    ) -> list[Memory]:
        """Global memories plus agent-scoped for this agent."""
        g_stmt = (
            select(Memory)
            .where(Memory.user_id == user_id, Memory.scope == MEMORY_SCOPE_GLOBAL)
            .order_by(Memory.created_at.asc())
        )
        a_stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.scope == MEMORY_SCOPE_AGENT,
                Memory.agent_id == agent_id,
            )
            .order_by(Memory.created_at.asc())
        )
        g = list((await self._session.execute(g_stmt)).scalars().all())
        a = list((await self._session.execute(a_stmt)).scalars().all())
        return g + a

    async def get_by_id(self, *, memory_id: uuid.UUID, user_id: uuid.UUID) -> Memory | None:
        stmt = select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete_by_id(self, *, memory_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        res = await self._session.execute(stmt)
        return res.rowcount > 0  # type: ignore[attr-defined]


__all__ = ["MemoryRepository"]
