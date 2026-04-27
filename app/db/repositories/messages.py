"""Репозиторий сообщений."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MESSAGE_TYPE_TEXT,
    Message,
)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        conversation_id: uuid.UUID,
        direction: str,
        text: str,
        message_type: str = MESSAGE_TYPE_TEXT,
        telegram_message_id: int | None = None,
        raw_update_json: dict[str, Any] | None = None,
        agent_id: str | None = None,
        skill_id: str | None = None,
        model_id: str | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            direction=direction,
            message_type=message_type,
            text=text,
            telegram_message_id=telegram_message_id,
            raw_update_json=raw_update_json,
            agent_id=agent_id,
            skill_id=skill_id,
            model_id=model_id,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_recent(
        self,
        *,
        conversation_id: uuid.UUID,
        limit: int,
        agent_id: str | None = None,
    ) -> list[Message]:
        """Возвращает последние N сообщений в хронологическом порядке."""
        if limit <= 0:
            return []
        conditions = [Message.conversation_id == conversation_id]
        if agent_id is not None:
            conditions.append(Message.agent_id == agent_id)
        stmt = select(Message).where(*conditions).order_by(Message.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        rows.reverse()
        return rows

    async def list_recent_for_agent(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_id: str,
        limit: int,
    ) -> list[Message]:
        """Возвращает последние N сообщений текущего агента в хронологическом порядке."""
        if limit <= 0:
            return []
        agent_condition = Message.agent_id == agent_id
        if agent_id == "general":
            agent_condition = or_(Message.agent_id == agent_id, Message.agent_id.is_(None))
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                agent_condition,
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        rows.reverse()
        return rows
