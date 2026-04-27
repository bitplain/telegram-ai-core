"""Streaming-рендерер для Telegram.

Поведение:
- В private чате: первый чанк — sendMessageDraft → запоминаем message_id →
  периодические editMessageText (throttle 400-700 мс, минимум +24 символа)
  → финал: либо обычный sendMessage, если уже отправили мало, либо финальный
  edit и затем sendMessage с дополнительными чанками для остатка > limit.
- В group/supergroup: сразу fallback (никаких драфтов): первый sendMessage
  и далее editMessageText по тому же message_id, пока размер не упрётся в лимит.
- При TelegramAPIError на send_message_draft — fallback на обычный send_message.
- sendChatAction "typing" — не чаще раз в TELEGRAM_CHAT_ACTION_INTERVAL_SECONDS.
- Никогда не вызываем edit с пустым текстом.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import ReplyParameters

from app.config import get_settings
from app.utils.text_splitter import split_for_telegram

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RenderedResult:
    """Результат рендера: финальный текст + список message_id, что улетели в чат."""

    final_text: str
    message_ids: list[int]
    used_draft: bool


def _strip_html(text: str) -> str:
    """Telegram умеет HTML только с whitelisted тегами. На этапе стрима безопаснее
    отдавать обычный текст и ничего не парсить — иначе незакрытые `<b>` от модели
    сломают edit. Делаем тривиальное HTML-эскейпирование, дальше работаем
    как с plain-текстом, отправляя без parse_mode."""
    return html.escape(text, quote=False)


class TelegramStreamRenderer:
    """Инкрементально доставляет токены LLM в Telegram-чат."""

    def __init__(
        self,
        bot: Bot,
        *,
        chat_id: int,
        chat_type: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        settings = get_settings()
        self._bot = bot
        self._chat_id = chat_id
        self._chat_type = chat_type
        self._reply_to_message_id = reply_to_message_id

        self._limit = settings.TELEGRAM_MESSAGE_MAX_CHARS
        self._min_interval = max(0.1, settings.TELEGRAM_DRAFT_MIN_INTERVAL_MS / 1000.0)
        self._min_delta_chars = max(1, settings.TELEGRAM_MIN_DELTA_CHARS)
        self._chat_action_interval = max(
            1.0, settings.TELEGRAM_CHAT_ACTION_INTERVAL_SECONDS
        )

        self._buffer: str = ""
        self._sent_text: str = ""
        self._current_message_id: int | None = None
        self._used_draft: bool = False
        self._first_send_ok: bool = False
        self._last_edit_ts: float = 0.0
        self._last_chat_action_ts: float = 0.0
        self._message_ids: list[int] = []

    @property
    def is_private(self) -> bool:
        return self._chat_type == "private"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Подаёт первый sendChatAction. Конкретное сообщение появится при первом дельт-куске."""
        await self._send_chat_action_throttled()

    async def push(self, delta: str) -> None:
        """Добавляет дельту от LLM в буфер и при необходимости обновляет Telegram."""
        if not delta:
            return
        self._buffer += delta
        await self._maybe_render()

    async def finalize(self) -> RenderedResult:
        """Завершает рендер. Доделывает все хвосты и возвращает результат."""
        # Если буфер пустой — обработать снаружи (обычно это означает
        # пустой ответ модели, отдадим пустой результат для проверки на handler-уровне).
        if not self._buffer:
            return RenderedResult(
                final_text="",
                message_ids=list(self._message_ids),
                used_draft=self._used_draft,
            )

        # Мы могли никогда не отправить первое сообщение, если стрим пришёл
        # одним куском — отправим его сейчас, без throttle.
        if self._current_message_id is None:
            await self._send_first(force=True)
        else:
            await self._maybe_render(force=True)

        # Если итоговый текст длиннее лимита — оставшийся хвост шлём
        # дополнительными send_message-сообщениями.
        if len(self._buffer) > self._limit:
            tail = self._buffer[self._limit :]
            self._buffer = self._buffer[: self._limit]
            await self._maybe_render(force=True)
            await self._send_tail(tail)

        return RenderedResult(
            final_text=self._buffer,
            message_ids=list(self._message_ids),
            used_draft=self._used_draft,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_chat_action_throttled(self) -> None:
        now = time.monotonic()
        if now - self._last_chat_action_ts < self._chat_action_interval:
            return
        self._last_chat_action_ts = now
        try:
            await self._bot.send_chat_action(chat_id=self._chat_id, action="typing")
        except TelegramAPIError:
            # Не критично — просто пропустим.
            log.debug("send_chat_action failed", exc_info=True)

    async def _maybe_render(self, *, force: bool = False) -> None:
        """Решает, отправлять ли первый message или edit-ить текущий."""
        if not self._buffer:
            return

        await self._send_chat_action_throttled()

        if self._current_message_id is None:
            # Первый кусок: либо sendMessageDraft (private), либо обычный send.
            await self._send_first(force=force)
            return

        # Edit-режим: ограничены лимитом, троттлингом и порогом по символам.
        text_to_show = self._buffer[: self._limit]
        if not force:
            now = time.monotonic()
            if now - self._last_edit_ts < self._min_interval:
                return
            if len(text_to_show) - len(self._sent_text) < self._min_delta_chars:
                return

        if not text_to_show or text_to_show == self._sent_text:
            return

        await self._edit_current(text_to_show)

    async def _send_first(self, *, force: bool) -> None:
        """Первая отправка: draft или fallback в зависимости от типа чата."""
        text_to_show = self._buffer[: self._limit]
        if not text_to_show:
            return

        # Throttle и минимальный размер действуют и для draft, кроме force.
        if not force:
            now = time.monotonic()
            if now - self._last_edit_ts < self._min_interval:
                return
            if len(text_to_show) < self._min_delta_chars:
                return

        if self.is_private:
            ok = await self._try_send_draft(text_to_show)
            if ok:
                return
        await self._send_first_fallback(text_to_show)

    def _build_reply_parameters(self) -> ReplyParameters | None:
        """Собирает ReplyParameters, если задан reply_to_message_id.

        В aiogram 3.26+ `send_message_draft` принимает только `reply_parameters`
        и падает с TypeError на устаревший kwarg `reply_to_message_id`.
        """
        if self._reply_to_message_id is None:
            return None
        return ReplyParameters(message_id=self._reply_to_message_id)

    async def _try_send_draft(self, text: str) -> bool:
        """Пробуем sendMessageDraft. Возвращаем True при успехе."""
        send_draft = getattr(self._bot, "send_message_draft", None)
        if send_draft is None:
            log.info("aiogram has no send_message_draft — falling back to send_message")
            return False

        reply_parameters = self._build_reply_parameters()
        kwargs: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": text,
        }
        if reply_parameters is not None:
            kwargs["reply_parameters"] = reply_parameters

        try:
            sent = await send_draft(**kwargs)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(exc.retry_after, 5))
            return False
        except TelegramAPIError as exc:
            log.warning(
                "send_message_draft failed (%s) — falling back to send_message",
                exc.__class__.__name__,
            )
            return False
        except Exception:  # noqa: BLE001
            # Любая иная ошибка (TypeError на несовместимый kwarg, AttributeError
            # на отсутствующий метод и т.д.) — деградируем в обычный send_message.
            log.exception(
                "send_message_draft raised unexpected exception; falling back to send_message"
            )
            return False

        if sent is None or not getattr(sent, "message_id", None):
            return False

        self._current_message_id = sent.message_id
        self._sent_text = text
        self._first_send_ok = True
        self._used_draft = True
        self._last_edit_ts = time.monotonic()
        self._message_ids.append(sent.message_id)
        return True

    async def _send_first_fallback(self, text: str) -> None:
        reply_parameters = self._build_reply_parameters()
        kwargs: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": text,
        }
        if reply_parameters is not None:
            kwargs["reply_parameters"] = reply_parameters

        try:
            sent = await self._bot.send_message(**kwargs)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(exc.retry_after, 5))
            return
        except TelegramAPIError:
            log.exception("send_message failed for chat %s", self._chat_id)
            return
        except Exception:  # noqa: BLE001
            log.exception(
                "send_message raised unexpected exception for chat %s",
                self._chat_id,
            )
            return

        self._current_message_id = sent.message_id
        self._sent_text = text
        self._first_send_ok = True
        self._used_draft = False
        self._last_edit_ts = time.monotonic()
        self._message_ids.append(sent.message_id)

    async def _edit_current(self, text: str) -> None:
        if self._current_message_id is None:
            return
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._current_message_id,
                text=text,
            )
            self._sent_text = text
            self._last_edit_ts = time.monotonic()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(exc.retry_after, 5))
        except TelegramAPIError as exc:
            msg = str(exc).lower()
            if "not modified" in msg:
                self._last_edit_ts = time.monotonic()
                return
            log.warning(
                "edit_message_text failed (%s); continuing", exc.__class__.__name__
            )
        except Exception:  # noqa: BLE001
            log.exception(
                "edit_message_text raised unexpected exception; continuing"
            )

    async def _send_tail(self, tail: str) -> None:
        """Длинный хвост, не вошедший в лимит первого сообщения, шлём пакетами."""
        chunks = split_for_telegram(tail, limit=self._limit)
        for chunk in chunks:
            if not chunk:
                continue
            try:
                sent = await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=chunk,
                )
                self._message_ids.append(sent.message_id)
            except TelegramAPIError:
                log.exception("Failed to send tail chunk to chat %s", self._chat_id)
                return


__all__ = ["TelegramStreamRenderer", "RenderedResult"]
