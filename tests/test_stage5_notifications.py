"""Тесты notification outbox (Stage 5), backoff и форматирования /notifications."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None

from app.bot.background_workers import (
    _maybe_trigger_eth_alert,
    _notification_delivery_tick,
)
from app.bot.notification_format import format_recent_notifications_text
from app.config import get_settings
from app.core.notification_backoff import compute_notification_backoff_seconds
from app.db.models import (
    ETH_ALERT_DIRECTION_ABOVE,
    NOTIFICATION_STATUS_FAILED,
    NOTIFICATION_STATUS_PENDING,
    NOTIFICATION_STATUS_PROCESSING,
    NOTIFICATION_STATUS_SENT,
    NOTIFICATION_TYPE_DAILY_DIGEST,
    NOTIFICATION_TYPE_ETH_ALERT,
    EthPriceAlert,
    NotificationOutbox,
    User,
)
from app.db.repositories.eth_alerts import EthPriceAlertRepository
from app.db.repositories.notification_outbox import NotificationOutboxRepository
from app.db.session import dispose_engine, init_engine, session_scope


def test_backoff_sequence_matches_spec() -> None:
    assert compute_notification_backoff_seconds(1) == 60
    assert compute_notification_backoff_seconds(2) == 300
    assert compute_notification_backoff_seconds(3) == 900
    assert compute_notification_backoff_seconds(4) == 3600
    assert compute_notification_backoff_seconds(5) == 21600
    assert compute_notification_backoff_seconds(6) == 86400
    assert compute_notification_backoff_seconds(99) == 86400


def test_format_recent_notifications_omits_payload_and_long_text() -> None:
    class Row:
        notification_type = "daily_digest"
        status = "sent"
        retry_count = 0
        created_at = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
        sent_at = datetime(2026, 4, 28, 12, 1, tzinfo=timezone.utc)
        last_error = None

    text = format_recent_notifications_text([Row()])
    assert "daily_digest" in text
    assert "sent" in text
    assert "digest_date" not in text
    assert "ETH" not in text

    class ErrRow:
        notification_type = "eth_alert"
        status = "failed"
        retry_count = 2
        created_at = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
        sent_at = None
        last_error = "x" * 200

    t2 = format_recent_notifications_text([ErrRow()])
    assert "…" in t2 or len(t2) < 500


async def _postgres_reachable() -> bool:
    if asyncpg is None:
        return False
    s = get_settings()
    if not s.database_url_native:
        return False
    try:
        conn = await asyncpg.connect(dsn=s.database_url_native, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _dispose_global_engine() -> None:
    yield
    try:
        asyncio.run(dispose_engine())
    except Exception:
        pass


@pytest.mark.asyncio
async def test_outbox_repository_lifecycle() -> None:
    if not await _postgres_reachable():
        pytest.skip("PostgreSQL unreachable for integration tests")

    init_engine()
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4()

    async with session_scope() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=9_000_000 + uuid.uuid4().int % 100_000,
                digest_enabled=False,
                created_at=now,
                updated_at=now,
            )
        )
    chat_id = -100229384756

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        row = await repo.create_notification(
            telegram_chat_id=chat_id,
            notification_type=NOTIFICATION_TYPE_ETH_ALERT,
            body="secret body",
            payload_json={"alert_id": str(uuid.uuid4())},
            user_id=uid,
        )
        assert row is not None
        nid = row.id

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        future = now + timedelta(hours=1)
        await session.execute(
            NotificationOutbox.__table__.update()
            .where(NotificationOutbox.id == nid)
            .values(next_retry_at=future)
        )
        claimed = await repo.claim_pending_notifications(10)
        assert claimed == []

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        await session.execute(
            NotificationOutbox.__table__.update()
            .where(NotificationOutbox.id == nid)
            .values(next_retry_at=now - timedelta(seconds=1))
        )
        claimed = await repo.claim_pending_notifications(10)
        assert len(claimed) == 1
        assert claimed[0].status == NOTIFICATION_STATUS_PROCESSING

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        await repo.mark_sent(nid)
        res = await session.get(NotificationOutbox, nid)
        assert res is not None
        assert res.status == NOTIFICATION_STATUS_SENT
        assert res.sent_at is not None


@pytest.mark.asyncio
async def test_digest_duplicate_same_utc_day() -> None:
    if not await _postgres_reachable():
        pytest.skip("PostgreSQL unreachable for integration tests")

    init_engine()
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4()
    d = "2026-04-28"

    async with session_scope() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=9_100_000 + uuid.uuid4().int % 50_000,
                digest_enabled=True,
                digest_telegram_chat_id=123,
                created_at=now,
                updated_at=now,
            )
        )

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        r1 = await repo.create_notification(
            telegram_chat_id=123,
            notification_type=NOTIFICATION_TYPE_DAILY_DIGEST,
            body="digest text one",
            payload_json={"digest_date": d},
            user_id=uid,
        )
        r2 = await repo.create_notification(
            telegram_chat_id=123,
            notification_type=NOTIFICATION_TYPE_DAILY_DIGEST,
            body="digest text two",
            payload_json={"digest_date": d},
            user_id=uid,
        )
        assert r1 is not None
        assert r2 is None


@pytest.mark.asyncio
async def test_mark_failed_for_retry_and_permanent() -> None:
    if not await _postgres_reachable():
        pytest.skip("PostgreSQL unreachable for integration tests")

    init_engine()
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4()

    async with session_scope() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=9_200_000 + uuid.uuid4().int % 40_000,
                created_at=now,
                updated_at=now,
            )
        )

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        row = await repo.create_notification(
            telegram_chat_id=1,
            notification_type=NOTIFICATION_TYPE_ETH_ALERT,
            body="x",
            payload_json={},
            user_id=uid,
            max_retries=2,
        )
        assert row is not None
        nid = row.id

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        await repo.mark_failed_for_retry(nid, "e1")
        r = await session.get(NotificationOutbox, nid)
        assert r is not None
        assert r.status == NOTIFICATION_STATUS_PENDING
        assert r.retry_count == 1

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        await repo.mark_failed_for_retry(nid, "e2")
        r = await session.get(NotificationOutbox, nid)
        assert r is not None
        assert r.status == NOTIFICATION_STATUS_FAILED


@pytest.mark.asyncio
async def test_eth_alert_enqueues_outbox_not_twice() -> None:
    if not await _postgres_reachable():
        pytest.skip("PostgreSQL unreachable for integration tests")

    init_engine()
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4()
    aid = uuid.uuid4()

    async with session_scope() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=9_300_000 + uuid.uuid4().int % 30_000,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            EthPriceAlert(
                id=aid,
                user_id=uid,
                telegram_chat_id=555,
                target_price_usd=Decimal("2000"),
                direction=ETH_ALERT_DIRECTION_ABOVE,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

    async with session_scope() as session:
        eth_repo = EthPriceAlertRepository(session)
        notif_repo = NotificationOutboxRepository(session)
        alert = await eth_repo.get_by_id(aid)
        assert alert is not None
        await _maybe_trigger_eth_alert(eth_repo, notif_repo, alert, Decimal("2500"))
        await session.refresh(alert)
        assert alert.notification_outbox_id is not None
        assert alert.is_active is False
        out_id = alert.notification_outbox_id

        await _maybe_trigger_eth_alert(eth_repo, notif_repo, alert, Decimal("3000"))
        await session.refresh(alert)
        assert alert.notification_outbox_id == out_id

    async with session_scope() as session:
        from sqlalchemy import func, select

        cnt = await session.scalar(
            select(func.count()).select_from(NotificationOutbox).where(
                NotificationOutbox.id == out_id
            )
        )
        assert cnt == 1


@pytest.mark.asyncio
async def test_delivery_updates_last_digest_sent_at() -> None:
    if not await _postgres_reachable():
        pytest.skip("PostgreSQL unreachable for integration tests")

    init_engine()
    now = datetime.now(timezone.utc)
    uid = uuid.uuid4()

    async with session_scope() as session:
        session.add(
            User(
                id=uid,
                telegram_user_id=9_400_000 + uuid.uuid4().int % 20_000,
                last_digest_sent_at=None,
                created_at=now,
                updated_at=now,
            )
        )

    async with session_scope() as session:
        repo = NotificationOutboxRepository(session)
        row = await repo.create_notification(
            telegram_chat_id=777,
            notification_type=NOTIFICATION_TYPE_DAILY_DIGEST,
            body="<b>digest</b>",
            payload_json={"digest_date": "2026-04-27"},
            user_id=uid,
            parse_mode="HTML",
        )
        assert row is not None
        nid = row.id

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))

    with patch(
        "app.bot.background_workers.commit_claim_pending_notifications",
        new_callable=AsyncMock,
    ) as mock_claim:
        mock_claim.return_value = [
            NotificationOutbox(
                id=nid,
                user_id=uid,
                telegram_chat_id=777,
                notification_type=NOTIFICATION_TYPE_DAILY_DIGEST,
                status=NOTIFICATION_STATUS_PROCESSING,
                payload_json={"digest_date": "2026-04-27"},
                body_text="<b>digest</b>",
                parse_mode="HTML",
                retry_count=0,
                max_retries=5,
                next_retry_at=now,
                created_at=now,
                updated_at=now,
            )
        ]
        await _notification_delivery_tick(bot, 10)

    bot.send_message.assert_awaited_once()

    async with session_scope() as session:
        user = await session.get(User, uid)
        assert user is not None
        assert user.last_digest_sent_at is not None
