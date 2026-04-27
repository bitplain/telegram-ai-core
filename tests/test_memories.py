"""Тесты таблицы memories и изоляции по user/agent."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import MEMORY_SCOPE_AGENT, MEMORY_SCOPE_GLOBAL, Memory, User
from app.db.repositories.memories import MemoryRepository


@pytest.fixture()
async def memory_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[User.__table__, Memory.__table__],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_list_delete_memory(memory_session) -> None:
    uid = uuid.uuid4()
    memory_session.add(
        User(
            id=uid,
            telegram_user_id=111,
            username=None,
            first_name=None,
            last_name=None,
            language_code=None,
        )
    )
    await memory_session.commit()

    repo = MemoryRepository(memory_session)
    m = await repo.create(
        user_id=uid, content="hello", scope=MEMORY_SCOPE_GLOBAL
    )
    await memory_session.commit()

    rows = await repo.list_for_user(user_id=uid, active_agent_id="crypto")
    assert len(rows) == 1
    assert rows[0].content == "hello"

    ok = await repo.delete_for_user(memory_id=m.id, user_id=uid)
    await memory_session.commit()
    assert ok
    rows2 = await repo.list_for_user(user_id=uid, active_agent_id="crypto")
    assert rows2 == []


@pytest.mark.asyncio
async def test_agent_memory_isolation(memory_session) -> None:
    uid = uuid.uuid4()
    memory_session.add(
        User(
            id=uid,
            telegram_user_id=222,
            username=None,
            first_name=None,
            last_name=None,
            language_code=None,
        )
    )
    await memory_session.commit()
    repo = MemoryRepository(memory_session)
    await repo.create(
        user_id=uid,
        content="for crypto only",
        scope=MEMORY_SCOPE_AGENT,
        agent_id="crypto",
    )
    await repo.create(
        user_id=uid,
        content="global note",
        scope=MEMORY_SCOPE_GLOBAL,
    )
    await memory_session.commit()

    llm_crypto = await repo.list_for_llm_context(
        user_id=uid, active_agent_id="crypto"
    )
    texts = {x.content for x in llm_crypto}
    assert "for crypto only" in texts
    assert "global note" in texts

    llm_news = await repo.list_for_llm_context(
        user_id=uid, active_agent_id="news"
    )
    texts_n = {x.content for x in llm_news}
    assert "for crypto only" not in texts_n
    assert "global note" in texts_n


def test_format_memory_system_suffix() -> None:
    from app.core.memory_context import format_memory_system_suffix

    uid = uuid.uuid4()
    mem = Memory(
        id=uuid.uuid4(),
        user_id=uid,
        agent_id=None,
        scope=MEMORY_SCOPE_GLOBAL,
        content="prefers short",
    )
    sfx = format_memory_system_suffix([mem])
    assert "prefers short" in sfx
    assert "долговремен" in sfx or "памят" in sfx.lower() or "пам" in sfx.lower()
