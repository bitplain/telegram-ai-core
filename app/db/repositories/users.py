"""Репозиторий пользователей."""

from __future__ import annotations

from datetime import datetime, timezone

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    """CRUD операции над пользователями Telegram."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        stmt = select(User).where(User.telegram_user_id == telegram_user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
    ) -> User:
        """Создаёт или обновляет запись пользователя."""
        user = await self.get_by_telegram_id(telegram_user_id)
        now = datetime.now(timezone.utc)
        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                created_at=now,
                updated_at=now,
            )
            self._session.add(user)
            await self._session.flush()
            return user

        changed = False
        if user.username != username:
            user.username = username
            changed = True
        if user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if user.last_name != last_name:
            user.last_name = last_name
            changed = True
        if user.language_code != language_code:
            user.language_code = language_code
            changed = True
        if changed:
            user.updated_at = now
            await self._session.flush()
        return user

    async def add_eth_balance(self, *, telegram_user_id: int, amount: float) -> User | None:
        user = await self.get_by_telegram_id(telegram_user_id)
        if user is None:
            return None
        new_bal = float(user.eth_balance or 0) + float(amount)
        user.eth_balance = new_bal  # type: ignore[assignment]
        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return user

    async def set_digest_enabled(
        self, *, telegram_user_id: int, enabled: bool
    ) -> User | None:
        user = await self.get_by_telegram_id(telegram_user_id)
        if user is None:
            return None
        user.digest_enabled = enabled
        user.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return user

    async def update_last_digest_sent(self, *, user_id: uuid.UUID) -> None:
        user = await self._session.get(User, user_id)
        if user is None:
            return
        user.last_digest_sent_at = datetime.now(timezone.utc)
        user.updated_at = user.last_digest_sent_at
        await self._session.flush()

    async def list_digest_enabled(self) -> list[User]:
        stmt = select(User).where(User.digest_enabled.is_(True))
        res = await self._session.execute(stmt)
        return list(res.scalars().all())
