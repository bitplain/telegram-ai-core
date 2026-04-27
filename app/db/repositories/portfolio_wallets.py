"""Watch-only wallet labels."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PortfolioWallet


class PortfolioWalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, *, user_id: uuid.UUID) -> list[PortfolioWallet]:
        stmt = (
            select(PortfolioWallet)
            .where(PortfolioWallet.user_id == user_id)
            .order_by(PortfolioWallet.network, PortfolioWallet.name)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def upsert_watch_only(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        network: str,
        address: str,
    ) -> PortfolioWallet:
        net = network.strip()[:64]
        addr = address.strip()[:256]
        nm = name.strip()[:128] or "wallet"
        stmt = select(PortfolioWallet).where(
            PortfolioWallet.user_id == user_id,
            PortfolioWallet.network == net,
            PortfolioWallet.address == addr,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.name = nm
            await self._session.flush()
            return existing
        row = PortfolioWallet(
            user_id=user_id,
            name=nm,
            network=net,
            address=addr,
        )
        self._session.add(row)
        await self._session.flush()
        return row


__all__ = ["PortfolioWalletRepository"]
