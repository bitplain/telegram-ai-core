"""Репозиторий сообщений."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
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
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            direction=direction,
            message_type=message_type,
            text=text,
            telegram_message_id=telegram_message_id,
            raw_update_json=raw_update_json,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_recent(
        self,
        *,
        conversation_id: uuid.UUID,
        limit: int,
    ) -> list[Message]:
        """Возвращает последние N сообщений в хронологическом порядке."""
        if limit <= 0:
            return []
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        rows.reverse()
        return rows
