"""Repository for manual portfolio positions (ETH MVP)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PortfolioAsset


def merge_eth_position(
    *,
    old_amount: Decimal,
    old_avg: Decimal,
    add_amount: Decimal,
    add_price: Decimal,
) -> tuple[Decimal, Decimal]:
    """Volume-weighted merge of a new buy into an existing ETH lot."""
    new_amt = old_amount + add_amount
    if new_amt <= 0:
        return Decimal("0"), old_avg
    new_avg = (old_amount * old_avg + add_amount * add_price) / new_amt
    return new_amt, new_avg


class PortfolioAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, *, user_id: uuid.UUID) -> list[PortfolioAsset]:
        stmt = (
            select(PortfolioAsset)
            .where(PortfolioAsset.user_id == user_id)
            .order_by(PortfolioAsset.symbol, PortfolioAsset.network)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_eth_row(
        self, *, user_id: uuid.UUID, network: str
    ) -> PortfolioAsset | None:
        stmt = select(PortfolioAsset).where(
            PortfolioAsset.user_id == user_id,
            PortfolioAsset.symbol == "ETH",
            PortfolioAsset.network == network,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert_eth_add(
        self,
        *,
        user_id: uuid.UUID,
        network: str,
        add_amount: Decimal,
        add_price: Decimal,
    ) -> PortfolioAsset:
        """Adds to ETH position on network; recomputes volume-weighted average price."""
        existing = await self.get_eth_row(user_id=user_id, network=network)
        if existing is None:
            row = PortfolioAsset(
                user_id=user_id,
                symbol="ETH",
                amount=add_amount,
                average_buy_price=add_price,
                network=network,
            )
            self._session.add(row)
            await self._session.flush()
            return row

        old_amt = Decimal(str(existing.amount))
        old_avg = Decimal(str(existing.average_buy_price))
        new_amt, new_avg = merge_eth_position(
            old_amount=old_amt,
            old_avg=old_avg,
            add_amount=add_amount,
            add_price=add_price,
        )
        existing.amount = new_amt
        existing.average_buy_price = new_avg
        await self._session.flush()
        return existing


__all__ = ["PortfolioAssetRepository", "merge_eth_position"]
