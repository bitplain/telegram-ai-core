"""Streaming renderer for Telegram with draft + edit fallback and no duplicates."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import ReplyParameters

from app.config import get_settings
from app.utils.text_splitter import DEFAULT_LIMIT, split_for_telegram

log = logging.getLogger(__name__)

_DRAFT_TEXT_LIMIT = 4096
_FALLBACK_PLACEHOLDER = "Генерирую ответ..."


@dataclass(slots=True)
class RenderedResult:
    final_text: str
    message_ids: list[int]
    used_draft: bool


class TelegramStreamRenderer:
    """Инкрементально доставляет LLM-текст в Telegram."""

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
        self._bot_token = settings.TELEGRAM_BOT_TOKEN

        self._final_limit = DEFAULT_LIMIT
        self._draft_limit = _DRAFT_TEXT_LIMIT
        self._edit_limit = settings.TELEGRAM_MESSAGE_MAX_CHARS
        self._min_interval = max(0.1, settings.TELEGRAM_DRAFT_UPDATE_INTERVAL_MS / 1000.0)
        self._min_delta_chars = max(1, settings.TELEGRAM_STREAM_MIN_CHARS_DELTA)
        self._draft_enabled = settings.TELEGRAM_STREAM_DRAFT_ENABLED
        self._edit_fallback_enabled = settings.TELEGRAM_STREAM_EDIT_FALLBACK_ENABLED
        self._chat_action_interval = max(1.0, settings.TELEGRAM_CHAT_ACTION_INTERVAL_SECONDS)

        self._buffer = ""
        self._sent_text = ""
        self._current_message_id: int | None = None
        self._used_draft = False
        self._using_edit_fallback = False
        self._stream_closed_for_length = False
        self._last_update_ts = 0.0
        self._last_chat_action_ts = 0.0
        self._message_ids: list[int] = []
        self._draft_id = int(time.time() * 1000) % 2_147_483_647 or 1

    @property
    def is_private(self) -> bool:
        return self._chat_type == "private"

    async def start(self) -> None:
        log.info("streaming_started", extra={"chat_id": self._chat_id, "chat_type": self._chat_type})
        await self._send_chat_action_throttled()

    async def push(self, delta: str) -> None:
        if not delta:
            return
        log.debug("streaming_chunk_received", extra={"chat_id": self._chat_id, "delta_chars": len(delta)})
        self._buffer += delta
        await self._maybe_render()

    async def finalize(self) -> RenderedResult:
        if not self._buffer:
            return RenderedResult(final_text="", message_ids=list(self._message_ids), used_draft=self._used_draft)

        first_chunk = self._buffer[: self._edit_limit]
        tail = self._buffer[self._edit_limit :]

        if self._current_message_id is None:
            await self._send_final_messages(self._buffer)
        else:
            # Не создаём второй "поток": финализируем уже видимое streaming-сообщение.
            if self._used_draft:
                ok = await self._try_send_draft(first_chunk[: self._draft_limit])
                if not ok and self._edit_fallback_enabled:
                    await self._edit_current(first_chunk)
            elif self._using_edit_fallback:
                await self._edit_current(first_chunk)

            if tail:
                await self._send_final_messages(tail)

        return RenderedResult(
            final_text=self._buffer,
            message_ids=list(self._message_ids),
            used_draft=self._used_draft,
        )

    async def _send_chat_action_throttled(self) -> None:
        now = time.monotonic()
        if now - self._last_chat_action_ts < self._chat_action_interval:
            return
        self._last_chat_action_ts = now
        try:
            await self._bot.send_chat_action(chat_id=self._chat_id, action="typing")
        except TelegramAPIError:
            log.debug("send_chat_action failed", exc_info=True)

    async def _maybe_render(self, *, force: bool = False) -> None:
        if not self._buffer or self._stream_closed_for_length:
            return
        await self._send_chat_action_throttled()

        text_to_show = self._buffer[: self._draft_limit if self._used_draft else self._edit_limit]
        if len(self._buffer) > self._edit_limit and self._using_edit_fallback:
            self._stream_closed_for_length = True
            return

        if not force and not self._should_update(text_to_show):
            return

        if self._current_message_id is None:
            await self._send_first(text_to_show)
            return

        if self._used_draft:
            ok = await self._try_send_draft(text_to_show)
            if ok:
                return
            await self._ensure_edit_fallback_started()
            return

        if self._using_edit_fallback:
            await self._edit_current(text_to_show)

    def _should_update(self, text_to_show: str) -> bool:
        if not text_to_show or text_to_show == self._sent_text:
            return False
        now = time.monotonic()
        if self._last_update_ts and now - self._last_update_ts < self._min_interval:
            return False
        if len(text_to_show) - len(self._sent_text) < self._min_delta_chars:
            return False
        return True

    async def _send_first(self, text: str) -> None:
        if not text:
            return
        if self.is_private and self._draft_enabled:
            ok = await self._try_send_draft(text[: self._draft_limit])
            if ok:
                return
            log.info("draft_update_failed_fallback_enabled", extra={"chat_id": self._chat_id})
        if self._edit_fallback_enabled:
            await self._send_first_fallback(_FALLBACK_PLACEHOLDER)
            if self._current_message_id is not None:
                await self._edit_current(text[: self._edit_limit])

    def _build_reply_parameters(self) -> ReplyParameters | None:
        if self._reply_to_message_id is None:
            return None
        return ReplyParameters(message_id=self._reply_to_message_id)

    async def _try_send_draft(self, text: str) -> bool:
        if not text or not self.is_private or not self._draft_enabled:
            return False
        text = text[: self._draft_limit]
        reply_parameters = self._build_reply_parameters()
        kwargs: dict[str, object] = {"chat_id": self._chat_id, "draft_id": self._draft_id, "text": text}
        if reply_parameters is not None:
            kwargs["reply_parameters"] = reply_parameters

        send_draft = getattr(self._bot, "send_message_draft", None)
        if send_draft is not None:
            try:
                sent = await send_draft(**kwargs)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(min(exc.retry_after, 5))
                return False
            except Exception:  # noqa: BLE001
                log.info("draft_update_failed_fallback_enabled", extra={"chat_id": self._chat_id})
                return False
        else:
            sent = await self._send_message_draft_raw(text=text, reply_parameters=reply_parameters)
            if sent is None:
                return False

        message_id = getattr(sent, "message_id", None) or (sent.get("message_id") if isinstance(sent, dict) else None)
        if not message_id:
            return False
        self._current_message_id = int(message_id)
        if int(message_id) not in self._message_ids:
            self._message_ids.append(int(message_id))
        self._sent_text = text
        self._used_draft = True
        self._using_edit_fallback = False
        self._last_update_ts = time.monotonic()
        log.info("draft_update_sent", extra={"chat_id": self._chat_id, "chars": len(text)})
        return True

    async def _send_message_draft_raw(self, *, text: str, reply_parameters: ReplyParameters | None) -> dict | None:
        if not self._bot_token:
            return None
        payload: dict[str, object] = {"chat_id": self._chat_id, "draft_id": self._draft_id, "text": text}
        if reply_parameters is not None:
            payload["reply_parameters"] = {"message_id": reply_parameters.message_id}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{self._bot_token}/sendMessageDraft",
                    json=payload,
                )
            if response.status_code >= 400:
                return None
            data = response.json()
        except Exception:  # noqa: BLE001
            log.info("draft_update_failed_fallback_enabled", extra={"chat_id": self._chat_id})
            return None
        result = data.get("result") if isinstance(data, dict) else None
        return result if isinstance(result, dict) else None

    async def _ensure_edit_fallback_started(self) -> None:
        if self._using_edit_fallback:
            return
        self._current_message_id = None
        self._sent_text = ""
        await self._send_first_fallback(_FALLBACK_PLACEHOLDER)
        if self._current_message_id is not None and self._buffer:
            await self._edit_current(self._buffer[: self._edit_limit])

    async def _send_first_fallback(self, text: str) -> None:
        if not text:
            return
        reply_parameters = self._build_reply_parameters()
        kwargs: dict[str, object] = {"chat_id": self._chat_id, "text": text}
        if reply_parameters is not None:
            kwargs["reply_parameters"] = reply_parameters
        try:
            sent = await self._bot.send_message(**kwargs)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(exc.retry_after, 5))
            return
        except Exception:  # noqa: BLE001
            log.exception("send_message fallback failed", extra={"chat_id": self._chat_id})
            return
        self._current_message_id = sent.message_id
        self._sent_text = text
        self._used_draft = False
        self._using_edit_fallback = True
        self._last_update_ts = time.monotonic()
        self._message_ids.append(sent.message_id)

    async def _edit_current(self, text: str) -> None:
        if not text or self._current_message_id is None or not self._edit_fallback_enabled:
            return
        text = text[: self._edit_limit]
        if text == self._sent_text:
            return
        try:
            await self._bot.edit_message_text(chat_id=self._chat_id, message_id=self._current_message_id, text=text)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(exc.retry_after, 5))
            return
        except TelegramAPIError as exc:
            if "not modified" in str(exc).lower():
                return
            log.warning("edit_message_text failed", extra={"chat_id": self._chat_id, "error_type": exc.__class__.__name__})
            return
        except Exception:  # noqa: BLE001
            log.exception("edit_message_text unexpected failure", extra={"chat_id": self._chat_id})
            return
        self._sent_text = text
        self._last_update_ts = time.monotonic()
        log.info("edit_fallback_update_sent", extra={"chat_id": self._chat_id, "chars": len(text)})

    async def _send_final_messages(self, text: str) -> None:
        for chunk in split_for_telegram(text, limit=self._final_limit):
            if not chunk:
                continue
            try:
                sent = await self._bot.send_message(chat_id=self._chat_id, text=chunk)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(min(exc.retry_after, 5))
                continue
            except Exception:  # noqa: BLE001
                log.exception("final_message_sent failed", extra={"chat_id": self._chat_id})
                return
            self._message_ids.append(sent.message_id)
            log.info("final_message_sent", extra={"chat_id": self._chat_id, "chars": len(chunk)})


__all__ = ["TelegramStreamRenderer", "RenderedResult"]
