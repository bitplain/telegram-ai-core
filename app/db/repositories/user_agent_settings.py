"""Repository для user-scoped настроек агентов."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserAgentSetting


class UserAgentSettingsRepository:
    """CRUD для ``user_agent_settings`` без бизнес-валидации."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_settings(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting | None:
        stmt = select(UserAgentSetting).where(
            UserAgentSetting.telegram_user_id == telegram_user_id,
            UserAgentSetting.agent_id == agent_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting:
        row = await self.get_settings(telegram_user_id, agent_id)
        if row is not None:
            return row
        row = UserAgentSetting(
            telegram_user_id=telegram_user_id,
            agent_id=agent_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def upsert_custom_prompt(
        self, telegram_user_id: int, agent_id: str, custom_prompt: str
    ) -> UserAgentSetting:
        row = await self._get_or_create(telegram_user_id, agent_id)
        row.custom_prompt = custom_prompt
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def reset_custom_prompt(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting:
        row = await self._get_or_create(telegram_user_id, agent_id)
        row.custom_prompt = None
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def upsert_model_id(
        self, telegram_user_id: int, agent_id: str, model_id: str
    ) -> UserAgentSetting:
        row = await self._get_or_create(telegram_user_id, agent_id)
        row.model_id = model_id
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def list_user_settings(self, telegram_user_id: int) -> list[UserAgentSetting]:
        stmt = (
            select(UserAgentSetting)
            .where(UserAgentSetting.telegram_user_id == telegram_user_id)
            .order_by(UserAgentSetting.agent_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["UserAgentSettingsRepository"]
