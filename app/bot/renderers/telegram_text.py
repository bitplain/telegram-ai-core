"""Утилиты для отправки больших и форматированных текстовых сообщений."""

from __future__ import annotations

import html
import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.utils.text_splitter import split_for_telegram

log = logging.getLogger(__name__)


def escape_html(text: str | None) -> str:
    """Безопасное экранирование текста для HTML parse_mode aiogram-а."""
    if not text:
        return ""
    return html.escape(text, quote=False)


async def send_long_html(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    limit: int = 3900,
    reply_to_message_id: int | None = None,
) -> list[int]:
    """Шлёт длинное HTML-сообщение, разбитое на куски ≤ ``limit`` символов.

    Возвращает список message_id отправленных кусков.
    Каждый кусок отправляется как обычный текст (parse_mode уже HTML по умолчанию).
    """
    chunks: Iterable[str] = split_for_telegram(text, limit=limit)
    message_ids: list[int] = []
    first = True
    for chunk in chunks:
        try:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=reply_to_message_id if first else None,
            )
            message_ids.append(sent.message_id)
        except TelegramAPIError:
            log.exception("Failed to send chunk to chat %s", chat_id)
            raise
        first = False
    return message_ids


async def send_plain(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    reply_to_message_id: int | None = None,
) -> int | None:
    """Шлёт короткое сообщение, без бросания наружу (логирует)."""
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
        )
        return sent.message_id
    except TelegramAPIError:
        log.exception("Failed to send plain message to chat %s", chat_id)
        return None


__all__ = ["escape_html", "send_long_html", "send_plain"]
