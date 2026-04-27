"""Репозиторий чатов."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_chat_id: int) -> Chat | None:
        stmt = select(Chat).where(Chat.telegram_chat_id == telegram_chat_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        telegram_chat_id: int,
        chat_type: str,
        title: str | None,
    ) -> Chat:
        chat = await self.get_by_telegram_id(telegram_chat_id)
        now = datetime.now(timezone.utc)
        if chat is None:
            chat = Chat(
                telegram_chat_id=telegram_chat_id,
                chat_type=chat_type,
                title=title,
                created_at=now,
                updated_at=now,
            )
            self._session.add(chat)
            await self._session.flush()
            return chat

        changed = False
        if chat.chat_type != chat_type:
            chat.chat_type = chat_type
            changed = True
        if chat.title != title:
            chat.title = title
            changed = True
        if changed:
            chat.updated_at = now
            await self._session.flush()
        return chat
