"""Репозиторий processed_updates для идемпотентности апдейтов Telegram."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProcessedUpdate


class ProcessedUpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_register(self, telegram_update_id: int) -> bool:
        """Пытается зарегистрировать update_id.

        Возвращает True если запись создана (то есть это первый просмотр),
        False если запись уже существовала (повторный апдейт).
        Используем INSERT ... ON CONFLICT DO NOTHING + RETURNING id.
        """
        stmt = (
            pg_insert(ProcessedUpdate)
            .values(telegram_update_id=telegram_update_id)
            .on_conflict_do_nothing(index_elements=[ProcessedUpdate.telegram_update_id])
            .returning(ProcessedUpdate.id)
        )
        result = await self._session.execute(stmt)
        inserted_id = result.scalar()
        return inserted_id is not None
