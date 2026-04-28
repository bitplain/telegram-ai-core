"""Фоновые воркеры: ETH alerts, daily digest, durable notification delivery."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings
from app.core.alert_logic import is_price_triggered
from app.core.services.digest_body import format_daily_digest_text, utc_today
from sqlalchemy import select

from app.db.models import (
    NOTIFICATION_TYPE_DAILY_DIGEST,
    NOTIFICATION_TYPE_ETH_ALERT,
    User,
    EthPriceAlert,
)
from app.db.repositories.eth_alerts import EthPriceAlertRepository
from app.db.repositories.notification_outbox import (
    NotificationOutboxRepository,
    commit_claim_pending_notifications,
)
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

log = logging.getLogger(__name__)

_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
_FETCH_TIMEOUT = 15.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def fetch_eth_price_usd_http(client: httpx.AsyncClient) -> Decimal:
    r = await client.get(
        _COINGECKO_URL,
        params={"ids": "ethereum", "vs_currencies": "usd"},
        timeout=_FETCH_TIMEOUT,
    )
    r.raise_for_status()
    data: dict[str, Any] = r.json()
    eth = data.get("ethereum") or {}
    raw = eth.get("usd")
    if raw is None:
        raise ValueError("ethereum.usd missing in Coingecko response")
    return Decimal(str(raw))


async def eth_alert_worker_loop() -> None:
    settings = get_settings()
    interval = max(5, int(getattr(settings, "ETH_ALERT_WORKER_INTERVAL_SECONDS", 60)))
    while True:
        try:
            await _eth_alert_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("eth_alert_worker_tick_failed")
        await asyncio.sleep(interval)


async def _eth_alert_tick() -> None:
    async with httpx.AsyncClient() as client:
        try:
            price = await fetch_eth_price_usd_http(client)
        except Exception:
            log.warning("eth_alert_price_fetch_failed")
            return

    async with session_scope() as session:
        eth_repo = EthPriceAlertRepository(session)
        notif_repo = NotificationOutboxRepository(session)
        alerts = await eth_repo.list_active()
        for alert in alerts:
            await _maybe_trigger_eth_alert(eth_repo, notif_repo, alert, price)


async def _maybe_trigger_eth_alert(
    eth_repo: EthPriceAlertRepository,
    notif_repo: NotificationOutboxRepository,
    alert: EthPriceAlert,
    current: Decimal,
) -> None:
    if alert.notification_outbox_id is not None:
        return
    target = Decimal(alert.target_price_usd)
    if not is_price_triggered(
        current_price_usd=current,
        target_price_usd=target,
        direction=alert.direction,
    ):
        return

    payload = {
        "alert_id": str(alert.id),
        "target_price_usd": str(target),
        "current_price_usd": str(current),
        "direction": alert.direction,
    }
    text = (
        f"ETH alert: цена {'≥' if alert.direction == 'above' else '≤'} "
        f"${target} (сейчас ~ ${current:.2f})."
    )
    row = await notif_repo.create_notification(
        telegram_chat_id=alert.telegram_chat_id,
        notification_type=NOTIFICATION_TYPE_ETH_ALERT,
        body=text,
        payload_json=payload,
        user_id=alert.user_id,
        parse_mode=None,
    )
    if row is None:
        return
    await eth_repo.attach_notification_and_deactivate(alert.id, row.id)
    log.info(
        "eth_alert_enqueued",
        extra={
            "notification_id": str(row.id),
            "alert_id": str(alert.id),
            "notification_type": NOTIFICATION_TYPE_ETH_ALERT,
        },
    )


async def daily_digest_worker_loop() -> None:
    settings = get_settings()
    interval = max(
        60,
        int(getattr(settings, "DAILY_DIGEST_WORKER_INTERVAL_SECONDS", 3600)),
    )
    while True:
        try:
            await _daily_digest_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("daily_digest_worker_tick_failed")
        await asyncio.sleep(interval)


async def _daily_digest_tick() -> None:
    today = utc_today()
    async with httpx.AsyncClient() as client:
        try:
            price = await fetch_eth_price_usd_http(client)
        except Exception:
            log.warning("daily_digest_price_fetch_failed")
            return

    async with session_scope() as session:
        notif_repo = NotificationOutboxRepository(session)
        stmt = select(User).where(
            User.digest_enabled.is_(True),
            User.digest_telegram_chat_id.isnot(None),
        )
        res = await session.execute(stmt)
        users = list(res.scalars().all())

        for user in users:
            chat_id = user.digest_telegram_chat_id
            if chat_id is None:
                continue
            if user.last_digest_sent_at is not None:
                sent_d = user.last_digest_sent_at.date()
                if sent_d == today:
                    continue

            digest_date = today
            body = format_daily_digest_text(
                digest_date=digest_date,
                eth_price_usd=price,
            )
            payload = {"digest_date": digest_date.isoformat()}
            row = await notif_repo.create_notification(
                telegram_chat_id=int(chat_id),
                notification_type=NOTIFICATION_TYPE_DAILY_DIGEST,
                body=body,
                payload_json=payload,
                user_id=user.id,
                parse_mode="HTML",
            )
            if row:
                log.info(
                    "daily_digest_enqueued",
                    extra={
                        "notification_id": str(row.id),
                        "user_id": str(user.id),
                        "notification_type": NOTIFICATION_TYPE_DAILY_DIGEST,
                    },
                )


async def notification_delivery_worker_loop(bot) -> None:
    settings = get_settings()
    interval = max(1, settings.NOTIFICATION_WORKER_INTERVAL_SECONDS)
    batch = max(1, settings.NOTIFICATION_WORKER_BATCH_SIZE)
    while True:
        try:
            await _notification_delivery_tick(bot, batch)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("notification_delivery_tick_outer_failed")
        await asyncio.sleep(interval)


async def _notification_delivery_tick(bot, batch: int) -> None:
    pending = await commit_claim_pending_notifications(batch)
    if not pending:
        return

    for n in pending:
        try:
            kwargs: dict[str, Any] = {
                "chat_id": n.telegram_chat_id,
                "text": n.body_text,
            }
            if n.parse_mode:
                kwargs["parse_mode"] = n.parse_mode
            await bot.send_message(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = str(exc)[:500]
            log.warning(
                "notification_send_failed",
                extra={
                    "notification_id": str(n.id),
                    "notification_type": n.notification_type,
                    "retry_count": n.retry_count,
                },
            )
            try:
                async with session_scope() as session:
                    repo = NotificationOutboxRepository(session)
                    await repo.mark_failed_for_retry(n.id, err)
            except Exception:
                log.exception(
                    "notification_mark_failed_error",
                    extra={"notification_id": str(n.id)},
                )
            continue

        try:
            async with session_scope() as session:
                repo = NotificationOutboxRepository(session)
                await repo.mark_sent(n.id)
                if n.notification_type == NOTIFICATION_TYPE_DAILY_DIGEST and n.user_id:
                    user_repo = UserRepository(session)
                    await user_repo.update_last_digest_sent_at(n.user_id, _utcnow())
                log.info(
                    "notification_sent",
                    extra={
                        "notification_id": str(n.id),
                        "notification_type": n.notification_type,
                        "status": "sent",
                    },
                )
        except Exception:
            log.exception(
                "notification_mark_sent_error",
                extra={"notification_id": str(n.id)},
            )


__all__ = [
    "eth_alert_worker_loop",
    "daily_digest_worker_loop",
    "notification_delivery_worker_loop",
    "fetch_eth_price_usd_http",
]
