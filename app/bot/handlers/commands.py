"""Хэндлеры команд: /start, /help, /reset, /status, /history, /agents, /agent,
/skills, /skill, /models, /model.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.agents.registry import get_agent_registry
from app.bot.renderers.telegram_text import escape_html, send_long_html, send_plain
from app.core.prompts import (
    HELP_MESSAGE,
    MODEL_NOT_ALLOWED_FOR_AGENT,
    START_MESSAGE,
    UNKNOWN_AGENT,
    UNKNOWN_MODEL,
    UNKNOWN_SKILL,
)
from app.db.models import (
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
)
from app.db.repositories.chats import ChatRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.repositories.messages import MessageRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope
from app.models.registry import get_model_registry
from app.skills.registry import get_skill_registry

log = logging.getLogger(__name__)

router = Router(name="commands")

# Все команды-алиасы для skill-ов тоже регистрируем здесь, чтобы они не
# попадали в общий messages-router как обычный текст.
SKILL_COMMAND_ALIASES = ("chat", "fast", "crypto", "finance", "news", "devops", "infra")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_conversation(message: Message):
    """Создаёт user/chat/conversation, если их ещё нет."""
    if message.from_user is None or message.chat is None:
        return None

    async with session_scope() as session:
        user_repo = UserRepository(session)
        chat_repo = ChatRepository(session)
        conv_repo = ConversationRepository(session)

        user = await user_repo.upsert(
            telegram_user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            language_code=message.from_user.language_code,
        )
        chat = await chat_repo.upsert(
            telegram_chat_id=message.chat.id,
            chat_type=message.chat.type,
            title=getattr(message.chat, "title", None),
        )
        conv = await conv_repo.get_or_create_active(
            user_id=user.id, chat_id=chat.id
        )
        return conv


# ---------------------------------------------------------------------------
# /start /help
# ---------------------------------------------------------------------------


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await _ensure_conversation(message)
    await send_plain(message.bot, message.chat.id, START_MESSAGE)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await send_plain(message.bot, message.chat.id, HELP_MESSAGE)


# ---------------------------------------------------------------------------
# /reset
# ---------------------------------------------------------------------------


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return

    async with session_scope() as session:
        user_repo = UserRepository(session)
        chat_repo = ChatRepository(session)
        conv_repo = ConversationRepository(session)

        user = await user_repo.get_by_telegram_id(message.from_user.id)
        chat = await chat_repo.get_by_telegram_id(message.chat.id)
        if user is None or chat is None:
            await send_plain(message.bot, message.chat.id, "Контекст уже пуст.")
            return

        active = await conv_repo.get_active(user_id=user.id, chat_id=chat.id)
        if active is None:
            await send_plain(message.bot, message.chat.id, "Контекст уже пуст.")
            return

        await conv_repo.reset(conversation_id=active.id)

    await send_plain(
        message.bot,
        message.chat.id,
        "Диалог сброшен. Следующее сообщение начнёт новый контекст.",
    )


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    conv = await _ensure_conversation(message)
    if conv is None:
        return

    agent = get_agent_registry().get(conv.active_agent_id)
    skill = get_skill_registry().get(conv.active_skill_id)
    model = get_model_registry().get(conv.active_model_id)

    text = (
        "<b>Текущий контекст диалога</b>\n"
        f"Агент: <code>{escape_html(agent.id)}</code> — {escape_html(agent.name)}\n"
        f"Навык: <code>{escape_html(skill.id)}</code> — {escape_html(skill.name)}\n"
        f"Модель: <code>{escape_html(model.id)}</code> — {escape_html(model.display_name)}\n"
        f"Провайдер: <code>{escape_html(model.provider)}</code> "
        f"({escape_html(model.model_name)})"
    )
    await send_plain(message.bot, message.chat.id, text)


# ---------------------------------------------------------------------------
# /history
# ---------------------------------------------------------------------------


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    conv = await _ensure_conversation(message)
    if conv is None:
        return

    async with session_scope() as session:
        msg_repo = MessageRepository(session)
        rows = await msg_repo.list_recent(conversation_id=conv.id, limit=20)

    if not rows:
        await send_plain(message.bot, message.chat.id, "История пока пустая.")
        return

    lines: list[str] = ["<b>Последние сообщения этого диалога:</b>"]
    for m in rows:
        if m.direction == MESSAGE_DIRECTION_INBOUND:
            prefix = "Вы"
        elif m.direction == MESSAGE_DIRECTION_OUTBOUND:
            prefix = "Бот"
        else:
            prefix = "Система"
        snippet = m.text if len(m.text) <= 500 else m.text[:497] + "..."
        lines.append(f"<b>{prefix}</b>: {escape_html(snippet)}")

    await send_long_html(message.bot, message.chat.id, "\n\n".join(lines))


# ---------------------------------------------------------------------------
# /agents и /agent <id>
# ---------------------------------------------------------------------------


@router.message(Command("agents"))
async def cmd_agents(message: Message) -> None:
    registry = get_agent_registry()
    agents = registry.list_enabled()
    lines = ["<b>Доступные агенты:</b>"]
    for a in agents:
        lines.append(
            f"• <code>{escape_html(a.id)}</code> — <b>{escape_html(a.name)}</b>: "
            f"{escape_html(a.description)}"
        )
    lines.append("\nВыбрать агента: /agent &lt;id&gt;")
    await send_long_html(message.bot, message.chat.id, "\n".join(lines))


@router.message(Command("agent"))
async def cmd_agent(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    if not args:
        await send_plain(
            message.bot, message.chat.id, "Использование: /agent &lt;id&gt;. Список — /agents."
        )
        return

    new_agent = get_agent_registry().get_or_none(args)
    if new_agent is None or not new_agent.enabled:
        await send_plain(message.bot, message.chat.id, UNKNOWN_AGENT)
        return

    conv = await _ensure_conversation(message)
    if conv is None:
        return

    # Если активная модель не разрешена в новом агенте — переключим на default агента.
    new_model_id = conv.active_model_id
    if new_agent.allowed_model_ids and new_model_id not in new_agent.allowed_model_ids:
        new_model_id = new_agent.default_model_id

    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id,
            agent_id=new_agent.id,
            model_id=new_model_id,
        )

    await send_plain(
        message.bot,
        message.chat.id,
        f"Активный агент изменён: <b>{escape_html(new_agent.name)}</b>.",
    )


# ---------------------------------------------------------------------------
# /skills и /skill <id>
# ---------------------------------------------------------------------------


@router.message(Command("skills"))
async def cmd_skills(message: Message) -> None:
    registry = get_skill_registry()
    skills = registry.list_enabled()
    lines = ["<b>Доступные навыки:</b>"]
    for s in skills:
        cmd_str = ", ".join(s.trigger_commands) if s.trigger_commands else "—"
        lines.append(
            f"• <code>{escape_html(s.id)}</code> — <b>{escape_html(s.name)}</b>: "
            f"{escape_html(s.description)} (команды: {escape_html(cmd_str)})"
        )
    lines.append("\nВыбрать навык: /skill &lt;id&gt;")
    await send_long_html(message.bot, message.chat.id, "\n".join(lines))


async def _activate_skill_by_id(message: Message, skill_id: str) -> None:
    """Общая логика для /skill <id> и команд-алиасов /chat, /crypto и т.д."""
    skill = get_skill_registry().get_or_none(skill_id)
    if skill is None or not skill.enabled:
        await send_plain(message.bot, message.chat.id, UNKNOWN_SKILL)
        return

    agent = get_agent_registry().get(skill.agent_id)

    new_model_id = skill.model_id or agent.default_model_id
    if agent.allowed_model_ids and new_model_id not in agent.allowed_model_ids:
        new_model_id = agent.default_model_id

    conv = await _ensure_conversation(message)
    if conv is None:
        return

    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id,
            agent_id=agent.id,
            skill_id=skill.id,
            model_id=new_model_id,
        )

    await send_plain(
        message.bot,
        message.chat.id,
        (
            f"Активный навык изменён: <b>{escape_html(skill.name)}</b>. "
            f"Теперь сообщения будут обрабатываться через агента: "
            f"<b>{escape_html(agent.name)}</b>."
        ),
    )


@router.message(Command("skill"))
async def cmd_skill(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    if not args:
        await send_plain(
            message.bot,
            message.chat.id,
            "Использование: /skill &lt;id&gt;. Список — /skills.",
        )
        return
    await _activate_skill_by_id(message, args)


# Алиасы /chat, /fast, /crypto, /finance, /news, /devops, /infra.
# Если у команды есть аргументы (текст после команды) — они уйдут в обычный
# обработчик messages, но сначала переключим skill. Чтобы не плодить
# дубликат логики, мы тут сразу делаем switch, а пользовательский текст
# (если есть) шлём в общий стрим как ещё одно сообщение.

@router.message(F.text.startswith("/"), F.text.regexp(r"^/(?:chat|fast|crypto|finance|news|devops|infra)(?:@\w+)?(?:\s|$)"))
async def cmd_skill_alias(message: Message) -> None:
    text = message.text or ""
    first_word, _, remainder = text.partition(" ")
    cmd = first_word.split("@", 1)[0].lstrip("/").lower()

    # /infra — это алиас devops.
    skill_id = "devops" if cmd == "infra" else cmd

    await _activate_skill_by_id(message, skill_id)

    # Если был текст после команды — пробрасываем его как обычное сообщение
    # тому же chat-у. Делаем это «вручную», чтобы не таскать circular import-ы.
    if remainder.strip():
        from app.bot.handlers.messages import process_user_message

        await process_user_message(message, override_text=remainder.strip())


# ---------------------------------------------------------------------------
# /models и /model <id>
# ---------------------------------------------------------------------------


@router.message(Command("models"))
async def cmd_models(message: Message) -> None:
    registry = get_model_registry()
    models = registry.list_enabled()
    lines = ["<b>Доступные модели:</b>"]
    for m in models:
        lines.append(
            f"• <code>{escape_html(m.id)}</code> — <b>{escape_html(m.display_name)}</b> "
            f"({escape_html(m.tier)}, {escape_html(m.provider)}/{escape_html(m.model_name)})"
        )
    lines.append("\nВыбрать модель: /model &lt;id&gt;")
    await send_long_html(message.bot, message.chat.id, "\n".join(lines))


@router.message(Command("model"))
async def cmd_model(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    if not args:
        await send_plain(
            message.bot,
            message.chat.id,
            "Использование: /model &lt;id&gt;. Список — /models.",
        )
        return

    model = get_model_registry().get_or_none(args)
    if model is None or not model.enabled:
        await send_plain(message.bot, message.chat.id, UNKNOWN_MODEL)
        return

    conv = await _ensure_conversation(message)
    if conv is None:
        return

    agent = get_agent_registry().get(conv.active_agent_id)
    if agent.allowed_model_ids and model.id not in agent.allowed_model_ids:
        await send_plain(message.bot, message.chat.id, MODEL_NOT_ALLOWED_FOR_AGENT)
        return

    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id, model_id=model.id
        )

    await send_plain(
        message.bot,
        message.chat.id,
        f"Активная модель изменена: <b>{escape_html(model.display_name)}</b>.",
    )


__all__ = ["router"]
