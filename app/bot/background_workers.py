"""Минимальные фоновые циклы: алерты по цене ETH и ежедневный дайджест."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.bot.renderers.telegram_text import send_long_html
from app.config import get_settings
from app.core.alert_logic import alert_should_fire
from app.core.price.eth import fetch_eth_usd_price
from app.core.services.digest_body import build_daily_digest_html
from app.db.repositories.eth_alerts import EthPriceAlertRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

log = logging.getLogger(__name__)


async def _alert_loop(bot: Bot) -> None:
    settings = get_settings()
    interval = max(60, int(settings.ETH_ALERT_CHECK_INTERVAL_SECONDS))
    while True:
        try:
            await asyncio.sleep(interval)
            price = await fetch_eth_usd_price()
            if price is None:
                continue
            async with session_scope() as session:
                repo = EthPriceAlertRepository(session)
                alerts = await repo.list_active()
            for alert in alerts:
                target = float(alert.target_price_usd)
                direction = alert.direction
                fire = alert_should_fire(
                    current_price_usd=price,
                    target_price_usd=target,
                    direction=direction,
                )
                if not fire:
                    continue
                text = (
                    "<b>Алерт ETH/USD</b>\n\n"
                    f"Цена сейчас: <b>${price:,.2f}</b>\n"
                    f"Твоя цель ({direction}): <b>${target:,.2f}</b>"
                )
                try:
                    await send_long_html(bot, alert.telegram_user_id, text)
                except TelegramAPIError:
                    log.warning(
                        "alert_send_failed",
                        extra={"telegram_user_id": alert.telegram_user_id},
                        exc_info=True,
                    )
                    continue
                async with session_scope() as session:
                    repo = EthPriceAlertRepository(session)
                    await repo.mark_triggered(alert.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("alert_loop_iteration_failed")


async def _digest_loop(bot: Bot) -> None:
    settings = get_settings()
    interval = max(60, int(settings.DAILY_DIGEST_POLL_INTERVAL_SECONDS))
    target_hour = int(settings.DAILY_DIGEST_HOUR_UTC) % 24
    while True:
        try:
            await asyncio.sleep(interval)
            now = datetime.now(timezone.utc)
            if now.hour != target_hour:
                continue
            today = now.date()
            async with session_scope() as session:
                user_repo = UserRepository(session)
                users = await user_repo.list_digest_enabled()
                for user in users:
                    last = user.last_digest_sent_at
                    if last is not None:
                        last_d = last.astimezone(timezone.utc).date()
                        if last_d >= today:
                            continue
                    try:
                        body = await build_daily_digest_html(
                            session, telegram_user_id=user.telegram_user_id
                        )
                        await send_long_html(bot, user.telegram_user_id, body)
                    except TelegramAPIError:
                        log.warning(
                            "digest_send_failed",
                            extra={"telegram_user_id": user.telegram_user_id},
                            exc_info=True,
                        )
                        continue
                    await user_repo.update_last_digest_sent(user_id=user.id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("digest_loop_iteration_failed")


def start_background_workers(bot: Bot) -> tuple[asyncio.Task, asyncio.Task]:
    """Запускает два asyncio.Task; caller отменяет при shutdown."""
    t1 = asyncio.create_task(_alert_loop(bot), name="eth-alerts")
    t2 = asyncio.create_task(_digest_loop(bot), name="daily-digest")
    return t1, t2


__all__ = ["start_background_workers"]
