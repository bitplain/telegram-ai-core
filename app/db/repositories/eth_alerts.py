"""Репозиторий ETH price alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EthPriceAlert


class EthAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        target_price_usd: Decimal,
        direction: str,
    ) -> EthPriceAlert:
        row = EthPriceAlert(
            user_id=user_id,
            target_price_usd=target_price_usd,
            direction=direction,
            is_active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_active_for_user(self, *, user_id: UUID) -> list[EthPriceAlert]:
        stmt = (
            select(EthPriceAlert)
            .where(
                EthPriceAlert.user_id == user_id,
                EthPriceAlert.is_active.is_(True),
                EthPriceAlert.triggered_at.is_(None),
            )
            .order_by(EthPriceAlert.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_all_for_user(self, *, user_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(EthPriceAlert)
            .where(
                EthPriceAlert.user_id == user_id,
                EthPriceAlert.is_active.is_(True),
                EthPriceAlert.triggered_at.is_(None),
            )
            .values(is_active=False, updated_at=now)
        )
        res = await self._session.execute(stmt)
        return int(res.rowcount or 0)

    async def list_active_globally(self) -> list[EthPriceAlert]:
        stmt = (
            select(EthPriceAlert)
            .where(
                EthPriceAlert.is_active.is_(True),
                EthPriceAlert.triggered_at.is_(None),
            )
            .order_by(EthPriceAlert.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_triggered(self, *, alert_id: UUID) -> bool:
        """Атомарно деактивирует один alert. Возвращает True, если строка обновлена."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(EthPriceAlert)
            .where(
                EthPriceAlert.id == alert_id,
                EthPriceAlert.is_active.is_(True),
                EthPriceAlert.triggered_at.is_(None),
            )
            .values(
                is_active=False,
                triggered_at=now,
                updated_at=now,
            )
        )
        res = await self._session.execute(stmt)
        return int(res.rowcount or 0) > 0


__all__ = ["EthAlertRepository"]
