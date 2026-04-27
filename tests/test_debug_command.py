"""Тесты доступа к команде /debug."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_debug_denied_when_admin_list_empty() -> None:
    from app.bot.handlers import commands as mod

    message = MagicMock()
    message.from_user = MagicMock(id=12345)
    message.chat = MagicMock(id=1)
    message.bot = MagicMock()

    with (
        patch.object(mod, "get_settings", return_value=MagicMock(admin_telegram_user_ids=[])),
        patch.object(mod, "send_plain", new_callable=AsyncMock) as send_plain,
    ):
        await mod.cmd_debug(message)

    send_plain.assert_awaited_once()
    _bot, _chat_id, text = send_plain.await_args[0]
    assert "только администратору" in text


@pytest.mark.asyncio
async def test_debug_denied_for_non_admin() -> None:
    from app.bot.handlers import commands as mod

    message = MagicMock()
    message.from_user = MagicMock(id=999)
    message.chat = MagicMock(id=1)
    message.bot = MagicMock()

    with (
        patch.object(
            mod,
            "get_settings",
            return_value=MagicMock(admin_telegram_user_ids=[1, 2]),
        ),
        patch.object(mod, "send_plain", new_callable=AsyncMock) as send_plain,
    ):
        await mod.cmd_debug(message)

    send_plain.assert_awaited_once()
