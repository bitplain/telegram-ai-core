"""Блокировка секретов до БД/LLM в process_user_message."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, User

SEED_12 = " ".join(["abandon"] * 12)


def _make_message(*, text: str) -> Message:
    bot = Bot("123456:ABC")
    return Message(
        message_id=1,
        date=0,
        chat=Chat(id=10, type="private"),
        from_user=User(id=42, is_bot=False, first_name="U"),
        text=text,
    )


@pytest.mark.asyncio
async def test_seed_phrase_blocked_before_idempotency() -> None:
    msg = _make_message(text=SEED_12)
    seen: list[int] = []

    async def track_first(uid: int) -> bool:  # noqa: ARG001
        seen.append(uid)
        return True

    with patch("app.bot.handlers.messages.is_first_seen", side_effect=track_first):
        with patch("app.bot.handlers.messages.send_plain", new=AsyncMock()) as sp:
            from app.bot.handlers import messages

            await messages.process_user_message(msg)

    assert seen == []
    out = str(sp.call_args[0][2])
    assert "секрет" in out or "сид" in out.lower() or "приват" in out.lower()


@pytest.mark.asyncio
async def test_private_key_hex_no_orchestrator() -> None:
    from app.bot.handlers import messages as msg_mod

    key = "0x" + "1" * 64
    msg = _make_message(text=f"key {key}")
    with patch.object(msg_mod, "is_first_seen", new=AsyncMock()) as is_first:
        with patch.object(msg_mod, "Orchestrator") as OrClass:
            with patch.object(msg_mod, "send_plain", new=AsyncMock()):
                await msg_mod.process_user_message(msg)
    is_first.assert_not_awaited()
    OrClass.assert_not_called()
