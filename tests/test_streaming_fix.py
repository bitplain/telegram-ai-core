"""Тесты фикса streaming-renderer-а: TypeError в send_message_draft → graceful fallback.

Проверяем, что:
1. Если ``send_message_draft`` бросает TypeError на устаревший kwarg — рендерер
   возвращает False (fallback на ``send_message``), а не валится наружу.
2. Если ``send_message`` тоже падает с произвольным Exception — рендерер
   логирует и тихо возвращается, не перебрасывая исключение.
3. ``ReplyParameters`` собирается, только если задан ``reply_to_message_id``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.bot.renderers.telegram_stream_renderer import TelegramStreamRenderer


class _FakeBot:
    """Минимальный mock aiogram Bot. Не зависит от httpx/Telegram."""

    def __init__(
        self,
        *,
        draft_exc: type[BaseException] | None = None,
        send_exc: type[BaseException] | None = None,
    ) -> None:
        self._draft_exc = draft_exc
        self._send_exc = send_exc
        self.draft_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []
        self.edit_calls: list[dict[str, Any]] = []
        self.chat_action_calls: list[dict[str, Any]] = []

    async def send_message_draft(self, **kwargs: Any) -> Any:
        self.draft_calls.append(kwargs)
        if self._draft_exc is not None:
            raise self._draft_exc("draft boom")
        return _SentMessage(message_id=42)

    async def send_message(self, **kwargs: Any) -> Any:
        self.send_calls.append(kwargs)
        if self._send_exc is not None:
            raise self._send_exc("send boom")
        return _SentMessage(message_id=43)

    async def edit_message_text(self, **kwargs: Any) -> Any:
        self.edit_calls.append(kwargs)
        return None

    async def send_chat_action(self, **kwargs: Any) -> None:
        self.chat_action_calls.append(kwargs)


class _SentMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


def _make_renderer(
    bot: _FakeBot, *, reply_to: int | None = None, chat_type: str = "private"
) -> TelegramStreamRenderer:
    return TelegramStreamRenderer(
        bot,  # type: ignore[arg-type]
        chat_id=12345,
        chat_type=chat_type,
        reply_to_message_id=reply_to,
    )


@pytest.mark.asyncio
async def test_draft_typeerror_returns_false_not_raises() -> None:
    """Главный кейс бага: aiogram 3.27 кидает TypeError на старый kwarg.

    После фикса рендерер ловит это в общем except Exception и возвращает False.
    """
    bot = _FakeBot(draft_exc=TypeError)
    renderer = _make_renderer(bot)
    ok = await renderer._try_send_draft("hello world")
    assert ok is False
    assert len(bot.draft_calls) == 1
    # Не оставляем «частичного» состояния.
    assert renderer._current_message_id is None
    assert renderer._used_draft is False


@pytest.mark.asyncio
async def test_draft_attributeerror_returns_false() -> None:
    """AttributeError тоже не должна валиться наружу."""
    bot = _FakeBot(draft_exc=AttributeError)
    renderer = _make_renderer(bot)
    ok = await renderer._try_send_draft("text")
    assert ok is False


@pytest.mark.asyncio
async def test_draft_success_records_message_id() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot)
    ok = await renderer._try_send_draft("text")
    assert ok is True
    assert renderer._current_message_id == 42
    assert renderer._used_draft is True
    assert renderer._message_ids == [42]


@pytest.mark.asyncio
async def test_send_first_fallback_swallows_unexpected_exceptions() -> None:
    """Если ``send_message`` (fallback) тоже падает — мы логируем и не падаем дальше."""
    bot = _FakeBot(send_exc=RuntimeError)
    renderer = _make_renderer(bot)
    # Не должно бросать.
    await renderer._send_first_fallback("text")
    assert renderer._current_message_id is None


@pytest.mark.asyncio
async def test_send_first_fallback_success() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot)
    await renderer._send_first_fallback("text")
    assert renderer._current_message_id == 43
    assert renderer._used_draft is False


@pytest.mark.asyncio
async def test_reply_parameters_built_only_when_reply_to_set() -> None:
    bot_no_reply = _FakeBot()
    renderer_no_reply = _make_renderer(bot_no_reply, reply_to=None)
    assert renderer_no_reply._build_reply_parameters() is None

    bot_with_reply = _FakeBot()
    renderer_with_reply = _make_renderer(bot_with_reply, reply_to=99)
    rp = renderer_with_reply._build_reply_parameters()
    assert rp is not None
    assert rp.message_id == 99


@pytest.mark.asyncio
async def test_draft_call_uses_reply_parameters_kwarg() -> None:
    """Проверяем, что в call попадает именно reply_parameters, а не reply_to_message_id."""
    bot = _FakeBot()
    renderer = _make_renderer(bot, reply_to=77)
    ok = await renderer._try_send_draft("text")
    assert ok is True
    assert len(bot.draft_calls) == 1
    call = bot.draft_calls[0]
    assert "reply_to_message_id" not in call
    assert "reply_parameters" in call
    assert call["reply_parameters"].message_id == 77


@pytest.mark.asyncio
async def test_draft_call_omits_reply_parameters_if_no_reply() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot, reply_to=None)
    ok = await renderer._try_send_draft("text")
    assert ok is True
    call = bot.draft_calls[0]
    assert "reply_parameters" not in call
    assert "reply_to_message_id" not in call


@pytest.mark.asyncio
async def test_draft_call_uses_integer_draft_id() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot)
    ok = await renderer._try_send_draft("text")

    assert ok is True
    draft_id = bot.draft_calls[0]["draft_id"]
    assert isinstance(draft_id, int)
    assert draft_id > 0


@pytest.mark.asyncio
async def test_group_chat_does_not_call_draft() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot, chat_type="supergroup")

    await renderer.push("x" * 30)

    assert bot.draft_calls == []
    assert len(bot.send_calls) == 1


@pytest.mark.asyncio
async def test_draft_failure_uses_send_message_fallback() -> None:
    bot = _FakeBot(draft_exc=RuntimeError)
    renderer = _make_renderer(bot)

    await renderer.push("x" * 30)

    assert len(bot.draft_calls) == 1
    assert len(bot.send_calls) == 1
    assert renderer._used_draft is False


@pytest.mark.asyncio
async def test_throttling_skips_small_delta_update() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot)

    await renderer.push("x" * 30)
    await renderer.push("small")

    assert len(bot.draft_calls) == 1
    assert bot.edit_calls == []


@pytest.mark.asyncio
async def test_finalize_does_not_duplicate_stream_message() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot)

    await renderer.push("x" * 30)
    await renderer.finalize()

    assert bot.send_calls == []
    assert len(bot.draft_calls) >= 1


@pytest.mark.asyncio
async def test_finalize_sends_message_when_no_stream_message_exists() -> None:
    bot = _FakeBot()
    renderer = _make_renderer(bot)
    renderer._buffer = "x" * 30

    await renderer.finalize()

    assert len(bot.send_calls) == 1
    assert bot.send_calls[0]["text"] == "x" * 30
