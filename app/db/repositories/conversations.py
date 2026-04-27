"""Репозиторий conversation-ов."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CONVERSATION_STATUS_ACTIVE,
    CONVERSATION_STATUS_CLOSED,
    Conversation,
)


class ConversationRepository:
    """Работа с активным conversation для пары (user, chat)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self, *, user_id: uuid.UUID, chat_id: uuid.UUID
    ) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.chat_id == chat_id,
            Conversation.status == CONVERSATION_STATUS_ACTIVE,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_active(
        self,
        *,
        user_id: uuid.UUID,
        chat_id: uuid.UUID,
        default_agent_id: str = "general",
        default_skill_id: str = "chat",
        default_model_id: str = "default_balanced",
    ) -> Conversation:
        existing = await self.get_active(user_id=user_id, chat_id=chat_id)
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        conversation = Conversation(
            user_id=user_id,
            chat_id=chat_id,
            status=CONVERSATION_STATUS_ACTIVE,
            active_agent_id=default_agent_id,
            active_skill_id=default_skill_id,
            active_model_id=default_model_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def update_active_routing(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_id: str | None = None,
        skill_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Обновляет активные agent/skill/model в conversation."""
        values: dict[str, object] = {"updated_at": datetime.now(timezone.utc)}
        if agent_id is not None:
            values["active_agent_id"] = agent_id
        if skill_id is not None:
            values["active_skill_id"] = skill_id
        if model_id is not None:
            values["active_model_id"] = model_id

        if len(values) == 1:
            return

        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**values)
        )
        await self._session.execute(stmt)

    async def reset(
        self,
        *,
        conversation_id: uuid.UUID,
    ) -> None:
        """Закрывает текущий conversation. /reset создаёт новый при следующем сообщении."""
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                status=CONVERSATION_STATUS_CLOSED,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._session.execute(stmt)
