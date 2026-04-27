"""Repository for manual portfolio holdings (MVP)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PortfolioAsset


def compute_weighted_average_buy_price(
    old_amount: Decimal,
    old_avg: Decimal,
    add_amount: Decimal,
    purchase_price: Decimal,
) -> Decimal:
    """New average after adding ``add_amount`` at ``purchase_price``."""
    total = old_amount + add_amount
    if total <= 0:
        return purchase_price
    return (old_amount * old_avg + add_amount * purchase_price) / total


class PortfolioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_assets(self, *, user_id: uuid.UUID) -> list[PortfolioAsset]:
        stmt = (
            select(PortfolioAsset)
            .where(PortfolioAsset.user_id == user_id)
            .order_by(PortfolioAsset.symbol.asc(), PortfolioAsset.network.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_eth_asset(
        self, *, user_id: uuid.UUID, network: str
    ) -> PortfolioAsset | None:
        stmt = select(PortfolioAsset).where(
            PortfolioAsset.user_id == user_id,
            PortfolioAsset.symbol == "ETH",
            PortfolioAsset.network == network,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add_eth_purchase(
        self,
        *,
        user_id: uuid.UUID,
        amount: Decimal,
        price: Decimal,
        network: str,
    ) -> PortfolioAsset:
        now = datetime.now(timezone.utc)
        existing = await self.get_eth_asset(user_id=user_id, network=network)
        if existing is None:
            row = PortfolioAsset(
                user_id=user_id,
                symbol="ETH",
                amount=amount,
                average_buy_price=price,
                network=network,
                updated_at=now,
            )
            self._session.add(row)
            await self._session.flush()
            return row

        old_amt = Decimal(str(existing.amount))
        old_avg = Decimal(str(existing.average_buy_price))
        new_avg = compute_weighted_average_buy_price(
            old_amt, old_avg, amount, price
        )
        existing.amount = old_amt + amount
        existing.average_buy_price = new_avg
        existing.updated_at = now
        await self._session.flush()
        return existing


__all__ = ["PortfolioRepository", "compute_weighted_average_buy_price"]
