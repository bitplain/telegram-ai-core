"""Фоновые asyncio-задачи: ETH price alerts и daily digest."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from aiogram import Bot

from app.config import get_settings
from app.core.services.digest_body import (
    build_daily_digest_text,
    digest_already_sent_for_utc_day,
)
from app.db.models import User
from app.db.repositories.chats import ChatRepository
from app.db.repositories.eth_alerts import EthAlertRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope
from app.llm.openrouter_client import OpenRouterError, get_openrouter_client
from app.core.settings_store import get_settings_store
from app.utils.formatting import format_decimal
from sqlalchemy import select

log = logging.getLogger(__name__)


async def _send_plain_safe(bot: Bot, chat_id: int, text: str) -> bool:
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception:  # noqa: BLE001
        log.exception("background_send_failed", extra={"chat_id": chat_id})
        return False


async def eth_alert_worker_loop(bot: Bot) -> None:
    settings = get_settings()
    interval = max(30, int(settings.ETH_ALERT_CHECK_INTERVAL_SECONDS))
    client = httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0))
    try:
        while True:
            try:
                from app.core.price.eth import fetch_eth_usd_price

                price = await fetch_eth_usd_price(client=client)
                if price is None:
                    await asyncio.sleep(interval)
                    continue

                async with session_scope() as session:
                    alert_repo = EthAlertRepository(session)
                    alerts = await alert_repo.list_active_globally()

                for alert in alerts:
                    try:
                        target = Decimal(alert.target_price_usd)
                        direction = alert.direction
                        hit = False
                        if direction == "above" and price >= target:
                            hit = True
                        elif direction == "below" and price <= target:
                            hit = True
                        if not hit:
                            continue

                        async with session_scope() as session:
                            ar = EthAlertRepository(session)
                            updated = await ar.mark_triggered(alert_id=alert.id)
                        if not updated:
                            continue

                        user_row = None
                        async with session_scope() as session:
                            ur = UserRepository(session)
                            cr = ChatRepository(session)
                            user_row = await ur.get_by_id(alert.user_id)
                            if user_row is None:
                                continue
                            chat = await cr.get_by_telegram_id(user_row.telegram_user_id)

                        if chat is None:
                            log.warning(
                                "eth_alert_no_private_chat",
                                extra={
                                    "alert_id": str(alert.id),
                                    "user_id": str(alert.user_id),
                                },
                            )
                            continue

                        msg = (
                            f"ETH alert сработал: цена ~{format_decimal(price)} USD "
                            f"(цель {format_decimal(target)} USD, направление: {direction})."
                        )
                        await _send_plain_safe(bot, chat.telegram_chat_id, msg)
                        log.info(
                            "eth_alert_triggered",
                            extra={
                                "alert_id": str(alert.id),
                                "user_id": str(alert.user_id),
                                "direction": direction,
                            },
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001
                        log.exception(
                            "eth_alert_iteration_error",
                            extra={"alert_id": str(alert.id)},
                        )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("eth_alert_worker_top_level_error")

            await asyncio.sleep(interval)
    finally:
        await client.aclose()


async def _digest_llm_summary() -> str | None:
    store = get_settings_store()
    api_key = await store.get_openrouter_api_key()
    if not api_key:
        return None
    client = get_openrouter_client()
    settings = get_settings()
    try:
        result = await client.chat_completion(
            model=settings.OPENROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Кратко (3–5 предложений, русский) опиши нейтрально настроение "
                        "крипторынка по заголовкам пользователя. Без гарантий доходности."
                    ),
                },
                {
                    "role": "user",
                    "content": "Сформируй общий нейтральный комментарий без персональных советов.",
                },
            ],
            temperature=0.2,
            max_tokens=400,
            api_key_override=api_key,
        )
        return (result.content or "").strip() or None
    except (OpenRouterError, Exception):  # noqa: BLE001
        log.debug("digest_llm_optional_failed", exc_info=False)
        return None


async def daily_digest_worker_loop(bot: Bot) -> None:
    interval = max(60, int(get_settings().DAILY_DIGEST_POLL_INTERVAL_SECONDS))
    client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    try:
        while True:
            try:
                settings = get_settings()
                if not settings.DAILY_DIGEST_ENABLED:
                    await asyncio.sleep(interval)
                    continue

                digest_hour = max(0, min(23, int(settings.DAILY_DIGEST_HOUR_UTC)))
                now = datetime.now(timezone.utc)
                if now.hour != digest_hour:
                    await asyncio.sleep(interval)
                    continue

                async with session_scope() as session:
                    stmt = select(User).where(User.digest_enabled.is_(True))
                    result = await session.execute(stmt)
                    candidates = list(result.scalars().all())

                today = now.date()
                for user in candidates:
                    try:
                        if digest_already_sent_for_utc_day(
                            last_sent_at=user.last_digest_sent_at, utc_day=today
                        ):
                            continue

                        llm_part = await _digest_llm_summary()
                        body = await build_daily_digest_text(
                            eth_balance=Decimal(user.eth_balance),
                            httpx_client=client,
                            llm_summary=llm_part,
                        )
                        ok = await _send_plain_safe(
                            bot, user.telegram_user_id, body
                        )
                        if ok:
                            sent_at = datetime.now(timezone.utc)
                            async with session_scope() as session:
                                ur = UserRepository(session)
                                await ur.update_last_digest_sent_at(
                                    user_id=user.id, sent_at=sent_at
                                )
                            log.info(
                                "daily_digest_sent",
                                extra={
                                    "user_id": str(user.id),
                                    "telegram_user_id": user.telegram_user_id,
                                },
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001
                        log.exception(
                            "daily_digest_user_error",
                            extra={"user_id": str(user.id)},
                        )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("daily_digest_worker_top_level_error")

            await asyncio.sleep(interval)
    finally:
        await client.aclose()


__all__ = ["eth_alert_worker_loop", "daily_digest_worker_loop"]
