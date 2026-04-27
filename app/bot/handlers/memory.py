"""Long-term memory: /remember, /memory, /forget_memory."""

from __future__ import annotations

import logging
import uuid

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bot.handlers.commands import _ensure_conversation
from app.bot.renderers.telegram_text import escape_html, send_long_html, send_plain
from app.core.sensitive_message_guard import BLOCK_MESSAGE, detect_sensitive_user_text
from app.db.models import MEMORY_SCOPE_AGENT, MEMORY_SCOPE_GLOBAL
from app.db.repositories.memories import MemoryRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope

log = logging.getLogger(__name__)

router = Router(name="memory")

_REMEMBER_HELP = (
    "<b>Сохранить глобальную заметку</b>\n"
    "/remember <i>текст</i>\n"
    "Пример: /remember Предпочитаю краткие ответы"
)
_MEMORY_HELP = (
    "<b>Память</b>\n"
    "/memory — список (global + текущий агент)\n"
    "/memory add_agent <i>текст</i> — для активного агента\n"
    f"{_REMEMBER_HELP}\n"
    "/forget_memory <i>id</i> — удалить"
)


@router.message(Command("remember"))
async def cmd_remember(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    raw = (command.args or "").strip()
    if not raw:
        await send_long_html(message.bot, message.chat.id, _REMEMBER_HELP)
        return
    sens = detect_sensitive_user_text(raw)
    if sens.blocked:
        log.info(
            "sensitive_remember_blocked",
            extra={"reason": sens.reason, "telegram_user_id": message.from_user.id},
        )
        await send_plain(message.bot, message.chat.id, BLOCK_MESSAGE)
        return

    await _ensure_conversation(message)
    async with session_scope() as session:
        urepo = UserRepository(session)
        user = await urepo.get_by_telegram_id(message.from_user.id)
        if user is None:
            return
        mrepo = MemoryRepository(session)
        m = await mrepo.create(
            user_id=user.id, content=raw, scope=MEMORY_SCOPE_GLOBAL
        )
    await send_long_html(
        message.bot,
        message.chat.id,
        f"Сохранено (global), id: <code>{m.id}</code> — /memory",
    )


@router.message(Command("forget_memory"))
async def cmd_forget_memory(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    arg = (command.args or "").strip()
    if not arg:
        await send_long_html(
            message.bot,
            message.chat.id,
            "Использование: /forget_memory <code>id</code> (UUID из /memory).",
        )
        return
    try:
        mid = uuid.UUID(arg.split()[0])
    except ValueError:
        await send_long_html(
            message.bot,
            message.chat.id,
            "Некорректный id. Пример UUID из списка /memory.",
        )
        return

    async with session_scope() as session:
        urepo = UserRepository(session)
        user = await urepo.get_by_telegram_id(message.from_user.id)
        if user is None:
            return
        mrepo = MemoryRepository(session)
        ok = await mrepo.delete_for_user(memory_id=mid, user_id=user.id)
    if ok:
        await send_plain(message.bot, message.chat.id, "Удалено.")
    else:
        await send_plain(message.bot, message.chat.id, "Запись не найдена или не твоя.")


@router.message(Command("memory"))
async def cmd_memory(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    args = (command.args or "").strip()
    if not args or args.lower() == "list":
        await _cmd_memory_list(message)
        return
    parts = args.split(maxsplit=1)
    if len(parts) >= 1 and parts[0].lower() == "add_agent":
        rest = parts[1].strip() if len(parts) > 1 else ""
        if not rest:
            await send_long_html(
                message.bot,
                message.chat.id,
                "Формат: /memory add_agent <i>текст</i>\n"
                "Пример: /memory add_agent чаще объясняй gas",
            )
            return
        sens = detect_sensitive_user_text(rest)
        if sens.blocked:
            log.info(
                "sensitive_memory_add_agent_blocked",
                extra={"reason": sens.reason, "telegram_user_id": message.from_user.id},
            )
            await send_plain(message.bot, message.chat.id, BLOCK_MESSAGE)
            return
        conv = await _ensure_conversation(message)
        if conv is None:
            return
        async with session_scope() as session:
            urepo = UserRepository(session)
            user = await urepo.get_by_telegram_id(message.from_user.id)
            if user is None:
                return
            mrepo = MemoryRepository(session)
            m = await mrepo.create(
                user_id=user.id,
                content=rest,
                scope=MEMORY_SCOPE_AGENT,
                agent_id=conv.active_agent_id,
            )
        await send_long_html(
            message.bot,
            message.chat.id,
            f"Сохранено для агента <code>{escape_html(conv.active_agent_id)}</code>, id: <code>{m.id}</code>",
        )
        return

    await send_long_html(message.bot, message.chat.id, _MEMORY_HELP)


async def _cmd_memory_list(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    conv = await _ensure_conversation(message)
    if conv is None:
        return
    async with session_scope() as session:
        urepo = UserRepository(session)
        user = await urepo.get_by_telegram_id(message.from_user.id)
        if user is None:
            return
        mrepo = MemoryRepository(session)
        rows = await mrepo.list_for_user(
            user_id=user.id, active_agent_id=conv.active_agent_id
        )
    if not rows:
        await send_long_html(
            message.bot,
            message.chat.id,
            "Память пуста. /remember или /memory add_agent <i>текст</i>",
        )
        return
    lines: list[str] = ["<b>Твоя память</b> (это не /history):", ""]
    for m in rows[:30]:
        if m.scope == MEMORY_SCOPE_AGENT:
            label = f"agent:{m.agent_id or '—'}"
        else:
            label = "global"
        short = m.content if len(m.content) <= 200 else m.content[:197] + "…"
        lines.append(
            f"<code>{m.id}</code> [{escape_html(label)}] {escape_html(short)}"
        )
    if len(rows) > 30:
        lines.append(f"… и ещё {len(rows) - 30}")
    await send_long_html(message.bot, message.chat.id, "\n".join(lines))


__all__ = ["router"]
