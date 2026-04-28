"""Репозиторий durable-уведомлений (outbox)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notification_backoff import compute_notification_backoff_seconds
from app.db.session import get_session_factory
from app.db.models import (
    NOTIFICATION_STATUS_FAILED,
    NOTIFICATION_STATUS_PENDING,
    NOTIFICATION_STATUS_PROCESSING,
    NOTIFICATION_STATUS_SENT,
    NOTIFICATION_TYPE_DAILY_DIGEST,
    NotificationOutbox,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

_STALE_PROCESSING_LOCK = 1800  # 30 minutes


class NotificationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_notification(
        self,
        *,
        telegram_chat_id: int,
        notification_type: str,
        body: str,
        payload_json: dict[str, Any],
        user_id: uuid.UUID | None = None,
        parse_mode: str | None = None,
        max_retries: int = 5,
    ) -> NotificationOutbox | None:
        """Создаёт запись. Для daily_digest не создаёт дубликат за тот же UTC-день."""
        if notification_type == NOTIFICATION_TYPE_DAILY_DIGEST and user_id is not None:
            digest_date = payload_json.get("digest_date")
            if digest_date:
                exists_stmt = (
                    select(NotificationOutbox.id)
                    .where(
                        NotificationOutbox.notification_type
                        == NOTIFICATION_TYPE_DAILY_DIGEST,
                        NotificationOutbox.user_id == user_id,
                        NotificationOutbox.status.in_(
                            (
                                NOTIFICATION_STATUS_PENDING,
                                NOTIFICATION_STATUS_PROCESSING,
                                NOTIFICATION_STATUS_SENT,
                            )
                        ),
                        NotificationOutbox.payload_json["digest_date"].astext
                        == str(digest_date),
                    )
                    .limit(1)
                )
                res = await self._session.execute(exists_stmt)
                if res.scalar_one_or_none() is not None:
                    return None

        now = _utcnow()
        row = NotificationOutbox(
            id=uuid.uuid4(),
            user_id=user_id,
            telegram_chat_id=telegram_chat_id,
            notification_type=notification_type,
            status=NOTIFICATION_STATUS_PENDING,
            payload_json=payload_json,
            body_text=body,
            parse_mode=parse_mode,
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def claim_pending_notifications(self, limit: int) -> list[NotificationOutbox]:
        """FOR UPDATE SKIP LOCKED; переводит в processing.

        Вызывающий обязан обернуть в транзакцию и закоммитить (см.
        ``commit_claim_pending_notifications``).
        """
        if limit <= 0:
            return []

        subq: Select[tuple[uuid.UUID]] = (
            select(NotificationOutbox.id)
            .where(
                NotificationOutbox.status == NOTIFICATION_STATUS_PENDING,
                NotificationOutbox.next_retry_at <= _utcnow(),
            )
            .order_by(NotificationOutbox.next_retry_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        res = await self._session.execute(subq)
        ids = [r[0] for r in res.all()]
        if not ids:
            return []

        now = _utcnow()
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id.in_(ids))
            .values(
                status=NOTIFICATION_STATUS_PROCESSING,
                locked_at=now,
                updated_at=now,
            )
        )
        stmt2 = select(NotificationOutbox).where(NotificationOutbox.id.in_(ids))
        rows = (await self._session.execute(stmt2)).scalars().all()
        return list(rows)

    async def reset_stale_processing_rows(self) -> None:
        """Возвращает зависшие processing-строки в pending (воркер умер посреди отправки)."""
        cutoff = _utcnow() - timedelta(seconds=_STALE_PROCESSING_LOCK)
        now = _utcnow()
        await self._session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.status == NOTIFICATION_STATUS_PROCESSING,
                NotificationOutbox.locked_at.isnot(None),
                NotificationOutbox.locked_at < cutoff,
            )
            .values(
                status=NOTIFICATION_STATUS_PENDING,
                locked_at=None,
                updated_at=now,
            )
        )

    async def mark_sent(self, notification_id: uuid.UUID) -> None:
        now = _utcnow()
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id == notification_id)
            .values(
                status=NOTIFICATION_STATUS_SENT,
                sent_at=now,
                locked_at=None,
                last_error=None,
                updated_at=now,
            )
        )

    async def mark_failed_for_retry(
        self,
        notification_id: uuid.UUID,
        error: str,
        *,
        next_retry_at: datetime | None = None,
    ) -> None:
        res = await self._session.execute(
            select(NotificationOutbox).where(NotificationOutbox.id == notification_id)
        )
        row = res.scalar_one_or_none()
        if row is None:
            return
        new_rc = row.retry_count + 1
        if new_rc >= row.max_retries:
            await self.mark_permanently_failed(notification_id, error)
            return

        if next_retry_at is None:
            delay = compute_notification_backoff_seconds(new_rc)
            next_retry_at = _utcnow() + timedelta(seconds=delay)
        now = _utcnow()
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id == notification_id)
            .values(
                status=NOTIFICATION_STATUS_PENDING,
                retry_count=new_rc,
                next_retry_at=next_retry_at,
                locked_at=None,
                last_error=error[:2000] if error else None,
                updated_at=now,
            )
        )

    async def mark_permanently_failed(self, notification_id: uuid.UUID, error: str) -> None:
        now = _utcnow()
        await self._session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id == notification_id)
            .values(
                status=NOTIFICATION_STATUS_FAILED,
                locked_at=None,
                last_error=error[:2000] if error else None,
                updated_at=now,
            )
        )

    async def list_recent_for_user(
        self, user_id: uuid.UUID, limit: int = 10
    ) -> list[NotificationOutbox]:
        stmt = (
            select(NotificationOutbox)
            .where(NotificationOutbox.user_id == user_id)
            .order_by(NotificationOutbox.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())


async def commit_claim_pending_notifications(limit: int) -> list[NotificationOutbox]:
    """Отдельная транзакция: claim + commit."""
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            repo = NotificationOutboxRepository(session)
            await repo.reset_stale_processing_rows()
            return await repo.claim_pending_notifications(limit)


__all__ = ["NotificationOutboxRepository", "commit_claim_pending_notifications"]
