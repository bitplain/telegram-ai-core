"""Репозиторий ценовых алертов ETH/USD."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EthPriceAlert


class EthPriceAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        telegram_user_id: int,
        target_price_usd: float,
        direction: str,
    ) -> EthPriceAlert:
        row = EthPriceAlert(
            user_id=user_id,
            telegram_user_id=telegram_user_id,
            target_price_usd=target_price_usd,
            direction=direction,
            is_active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_active(self) -> list[EthPriceAlert]:
        stmt = (
            select(EthPriceAlert)
            .where(EthPriceAlert.is_active.is_(True))
            .order_by(EthPriceAlert.created_at.asc())
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def mark_triggered(self, alert_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(EthPriceAlert)
            .where(EthPriceAlert.id == alert_id)
            .values(is_active=False, triggered_at=now)
        )
