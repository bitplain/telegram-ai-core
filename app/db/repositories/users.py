"""Репозиторий пользователей."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

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

    async def add_eth_purchase(
        self,
        *,
        telegram_user_id: int,
        amount: Decimal,
        price_usd_per_eth: float | None,
    ) -> User:
        """Добавляет ETH к балансу и обновляет суммарную себестоимость в USD."""
        user = await self.get_by_telegram_id(telegram_user_id)
        if user is None:
            raise ValueError("user_not_found")
        now = datetime.now(timezone.utc)
        if amount <= 0:
            raise ValueError("amount_invalid")
        new_bal = user.eth_balance + amount
        new_basis = user.eth_cost_basis_usd
        if price_usd_per_eth is not None and price_usd_per_eth > 0:
            add_cost = float(amount) * float(price_usd_per_eth)
            new_basis = (new_basis or 0.0) + add_cost
        user.eth_balance = new_bal
        user.eth_cost_basis_usd = new_basis
        user.updated_at = now
        await self._session.flush()
        return user
