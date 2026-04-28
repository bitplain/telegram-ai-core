"""Репозиторий ETH price alerts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EthPriceAlert


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EthPriceAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_alert(
        self,
        *,
        user_id: uuid.UUID,
        telegram_chat_id: int,
        target_price_usd: Decimal,
        direction: str,
    ) -> EthPriceAlert:
        now = _utcnow()
        row = EthPriceAlert(
            id=uuid.uuid4(),
            user_id=user_id,
            telegram_chat_id=telegram_chat_id,
            target_price_usd=target_price_usd,
            direction=direction,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_active(self) -> list[EthPriceAlert]:
        stmt = select(EthPriceAlert).where(EthPriceAlert.is_active.is_(True))
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def list_for_user(
        self, user_id: uuid.UUID, *, active_only: bool = False
    ) -> list[EthPriceAlert]:
        stmt = select(EthPriceAlert).where(EthPriceAlert.user_id == user_id)
        if active_only:
            stmt = stmt.where(EthPriceAlert.is_active.is_(True))
        stmt = stmt.order_by(EthPriceAlert.created_at.desc())
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def get_by_id(self, alert_id: uuid.UUID) -> EthPriceAlert | None:
        stmt = select(EthPriceAlert).where(EthPriceAlert.id == alert_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def attach_notification_and_deactivate(
        self,
        alert_id: uuid.UUID,
        notification_outbox_id: uuid.UUID,
    ) -> None:
        row = await self.get_by_id(alert_id)
        if row is None:
            return
        now = _utcnow()
        row.is_active = False
        row.triggered_at = now
        row.notification_outbox_id = notification_outbox_id
        row.updated_at = now
        await self._session.flush()


__all__ = ["EthPriceAlertRepository"]
