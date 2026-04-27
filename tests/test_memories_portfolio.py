"""Memory repository and portfolio weighted average."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Memory, PortfolioAsset, User
from app.db.repositories.memories import MemoryRepository
from app.db.repositories.portfolio import (
    PortfolioRepository,
    compute_weighted_average_buy_price,
)


@pytest.mark.asyncio
async def test_memory_create_list_delete_isolation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: User.__table__.create(sync_conn, checkfirst=True)
        )
        await conn.run_sync(
            lambda sync_conn: Memory.__table__.create(sync_conn, checkfirst=True)
        )

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    uid = uuid.uuid4()
    other_uid = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=111,
                username=None,
                first_name=None,
                last_name=None,
                language_code=None,
            )
        )
        session.add(
            User(
                id=other_uid,
                telegram_user_id=222,
                username=None,
                first_name=None,
                last_name=None,
                language_code=None,
            )
        )
        await session.commit()

    async with factory() as session:
        repo = MemoryRepository(session)
        g1 = await repo.create_memory(
            user_id=uid, content="note a", scope="global", agent_id=None
        )
        await repo.create_memory(
            user_id=uid,
            content="agent note",
            scope="agent",
            agent_id="crypto",
        )
        await repo.create_memory(
            user_id=uid,
            content="other agent",
            scope="agent",
            agent_id="news",
        )
        await session.commit()

    async with factory() as session:
        repo = MemoryRepository(session)
        globs = await repo.list_global_memories(user_id=uid)
        crypto_mem = await repo.list_agent_memories(user_id=uid, agent_id="crypto")
        assert len(globs) == 1
        assert globs[0].id == g1.id
        assert len(crypto_mem) == 1
        assert crypto_mem[0].content == "agent note"

    async with factory() as session:
        repo = MemoryRepository(session)
        assert await repo.delete_memory(memory_id=g1.id, user_id=other_uid) is False
        assert await repo.delete_memory(memory_id=g1.id, user_id=uid) is True
        await session.commit()

    async with factory() as session:
        repo = MemoryRepository(session)
        assert await repo.list_global_memories(user_id=uid) == []

    await engine.dispose()


def test_weighted_average_buy_price() -> None:
    assert compute_weighted_average_buy_price(
        Decimal("1"), Decimal("100"), Decimal("1"), Decimal("200")
    ) == Decimal("150")
    assert compute_weighted_average_buy_price(
        Decimal("0.5"), Decimal("3200"), Decimal("0.5"), Decimal("2800")
    ) == Decimal("3000")


@pytest.mark.asyncio
async def test_portfolio_add_eth_recalculates_average() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: User.__table__.create(sync_conn, checkfirst=True)
        )
        await conn.run_sync(
            lambda sync_conn: PortfolioAsset.__table__.create(
                sync_conn, checkfirst=True
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    uid = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=333,
                username=None,
                first_name=None,
                last_name=None,
                language_code=None,
            )
        )
        await session.commit()

    async with factory() as session:
        repo = PortfolioRepository(session)
        r1 = await repo.add_eth_purchase(
            user_id=uid,
            amount=Decimal("1"),
            price=Decimal("100"),
            network="mainnet",
        )
        assert r1.amount == Decimal("1")
        assert r1.average_buy_price == Decimal("100")
        r2 = await repo.add_eth_purchase(
            user_id=uid,
            amount=Decimal("1"),
            price=Decimal("200"),
            network="mainnet",
        )
        await session.commit()
        assert r2.amount == Decimal("2")
        assert r2.average_buy_price == Decimal("150")

    await engine.dispose()
