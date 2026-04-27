"""Репозиторий долговременной памяти пользователя."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MEMORY_SCOPE_AGENT, MEMORY_SCOPE_GLOBAL, Memory


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        content: str,
        scope: str,
        agent_id: str | None = None,
    ) -> Memory:
        now = datetime.now(timezone.utc)
        m = Memory(
            user_id=user_id,
            content=content.strip(),
            scope=scope,
            agent_id=agent_id if scope == MEMORY_SCOPE_AGENT else None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(m)
        await self._session.flush()
        return m

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        active_agent_id: str | None = None,
    ) -> list[Memory]:
        """Global + (опционально) agent-scoped для активного агента."""
        agent_part = and_(
            Memory.scope == MEMORY_SCOPE_AGENT,
            Memory.agent_id == active_agent_id,
        )
        global_part = Memory.scope == MEMORY_SCOPE_GLOBAL
        if active_agent_id:
            stmt = select(Memory).where(
                and_(Memory.user_id == user_id, or_(global_part, agent_part))
            )
        else:
            stmt = select(Memory).where(
                and_(Memory.user_id == user_id, global_part)
            )
        stmt = stmt.order_by(Memory.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_llm_context(
        self,
        *,
        user_id: uuid.UUID,
        active_agent_id: str,
    ) -> list[Memory]:
        """Память для prompt: global + agent для текущего агента."""
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                or_(
                    Memory.scope == MEMORY_SCOPE_GLOBAL,
                    and_(
                        Memory.scope == MEMORY_SCOPE_AGENT,
                        Memory.agent_id == active_agent_id,
                    ),
                ),
            )
            .order_by(Memory.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_for_user(
        self, *, memory_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        stmt = (
            delete(Memory)
            .where(and_(Memory.id == memory_id, Memory.user_id == user_id))
            .returning(Memory.id)
        )
        res = await self._session.execute(stmt)
        row = res.scalar_one_or_none()
        return row is not None
