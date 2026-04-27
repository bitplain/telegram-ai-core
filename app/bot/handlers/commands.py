"""Хэндлеры команд: /start, /help, /reset, /status, /history, /agents, /agent,
/skills, /skill, /models, /model.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.agents.registry import get_agent_registry
from app.bot.renderers.telegram_text import escape_html, send_long_html, send_plain
from app.api.health import ready
from app.config import get_settings
from app.core.agent_modes import (
    AGENT_MODE_AGENT,
    AGENT_MODE_DEFAULT,
    available_agent_mode_ids,
    build_agent_mode_activation,
    build_default_mode_activation,
)
from app.core.prompts import (
    HELP_MESSAGE,
    MODEL_NOT_ALLOWED_FOR_AGENT,
    START_MESSAGE,
    UNKNOWN_AGENT,
    UNKNOWN_MODEL,
    UNKNOWN_SKILL,
)
from app.core.settings_store import get_settings_store
from app.db.models import (
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
)
from app.db.repositories.chats import ChatRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.repositories.messages import MessageRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope
from app.redis.client import ping as redis_ping
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
    pg_status = "unknown"
    redis_status = "unknown"
    try:
        from app.api.diagnostics import _check_postgres, _check_redis

        pg_info = await _check_postgres()
        redis_info = await _check_redis()
        pg_status = "ok" if pg_info.get("ok") else "error"
        redis_status = "ok" if redis_info.get("ok") else "error"
    except Exception:  # noqa: BLE001
        log.exception("Failed to build dependency status for /status")

    lines = [
        "<b>Статус</b>",
        "",
        "App status: ok",
        f"Telegram mode: <code>{escape_html(get_settings().TELEGRAM_MODE)}</code>",
        f"Режим: <code>{escape_html(conv.active_mode)}</code>",
        f"Активный агент: <b>{escape_html(agent.name)}</b>",
        f"Active agent id: <code>{escape_html(agent.id)}</code>",
        f"Навык: <code>{escape_html(skill.id)}</code>",
        f"Модель: <code>{escape_html(model.id)}</code>",
        f"Provider: <code>{escape_html(model.provider)}</code>",
        f"Provider model: <code>{escape_html(model.model_name)}</code>",
        f"PostgreSQL: <b>{escape_html(pg_status)}</b>",
        f"Redis: <b>{escape_html(redis_status)}</b>",
    ]

    if message.from_user is not None:
        admin_ids = get_settings().admin_telegram_user_ids
        if message.from_user.id in admin_ids:
            store = get_settings_store()
            api_key = await store.get_openrouter_api_key()
            has_db_key = await store.has_db_openrouter_api_key()
            if api_key and has_db_key:
                source = "db"
            elif api_key:
                source = "env"
            else:
                source = "не задан"
            lines.append(f"OpenRouter API key: <b>{escape_html(source)}</b>")
            override = await store.get_model_override(model.id)
            if override:
                lines.append(
                    f"Override активной модели: <code>{escape_html(override)}</code>"
                )

    await send_plain(message.bot, message.chat.id, "\n".join(lines))


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


def _agent_menu_keyboard(*, show_exit: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Криптовалютный аналитик", callback_data="agent:select:crypto")],
        [InlineKeyboardButton(text="Новостной агент", callback_data="agent:select:news")],
    ]
    if show_exit:
        rows.append([InlineKeyboardButton(text="Выйти в обычный режим", callback_data="agent:exit")])
    rows.extend(
        [
            [InlineKeyboardButton(text="Настройки агентов", callback_data="agent:settings")],
            [InlineKeyboardButton(text="Закрыть", callback_data="agent:close")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _agent_menu_text(active_mode: str, active_agent_id: str) -> str:
    registry = get_agent_registry()
    active_agent = registry.get(active_agent_id)
    agents = registry.list_agent_menu_enabled()
    lines = [
        "<b>Режимы агентов</b>",
        "",
        f"Текущий режим: <code>{escape_html(active_mode)}</code>",
        f"Активный агент: <b>{escape_html(active_agent.name)}</b>",
        "",
        "Доступные специализированные агенты:",
    ]
    for agent in agents:
        lines.append(f"• <code>{escape_html(agent.id)}</code> — {escape_html(agent.name)}")
    return "\n".join(lines)


def _available_agents_error() -> str:
    ids = ", ".join(available_agent_mode_ids()) or "нет доступных спецагентов"
    return f"{UNKNOWN_AGENT}\n\nДоступные специализированные агенты: <code>{escape_html(ids)}</code>."


async def _render_agent_menu(message: Message) -> None:
    conv = await _ensure_conversation(message)
    if conv is None:
        return
    await _send_agent_menu_message(message, conv.active_mode, conv.active_agent_id)


async def _send_agent_menu_message(
    message: Message,
    active_mode: str,
    active_agent_id: str,
) -> None:
    await message.answer(
        _agent_menu_text(active_mode, active_agent_id),
        reply_markup=_agent_menu_keyboard(show_exit=active_mode == AGENT_MODE_AGENT),
    )


async def _activate_agent_mode_for_message(message: Message, agent_id: str) -> None:
    conv = await _ensure_conversation(message)
    if conv is None:
        return
    try:
        activation = build_agent_mode_activation(agent_id)
    except ValueError:
        await send_plain(message.bot, message.chat.id, _available_agents_error())
        return
    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id,
            active_mode=AGENT_MODE_DEFAULT,
            agent_id=activation.active_agent_id,
            skill_id=activation.active_skill_id,
            model_id=activation.active_model_id,
        )
    await send_plain(message.bot, message.chat.id, _agent_enabled_text(activation.agent.name))


async def _activate_agent_mode_for_callback(callback: CallbackQuery, agent_id: str) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    conv = await _ensure_conversation(callback.message)
    if conv is None:
        await callback.answer()
        return
    try:
        activation = build_agent_mode_activation(agent_id)
    except ValueError:
        await callback.answer("Агент не найден", show_alert=True)
        return
    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id,
            active_mode=activation.active_mode,
            agent_id=activation.active_agent_id,
            skill_id=activation.active_skill_id,
            model_id=activation.active_model_id,
        )
    await callback.message.answer(_agent_enabled_text(activation.agent.name))
    await callback.answer("Режим включён")


def _agent_enabled_text(agent_name: str) -> str:
    return (
        f"Режим включён: {escape_html(agent_name)}.\n\n"
        "Теперь все сообщения будут обрабатываться этим агентом.\n\n"
        "Чтобы выйти, используй /exit."
    )


@router.message(Command("agent"))
async def cmd_agent(message: Message, command: CommandObject) -> None:
    args = (command.args or "").strip()
    if not args:
        await _render_agent_menu(message)
        return
    await _activate_agent_mode_for_message(message, args.lower())


@router.message(Command("exit"))
async def cmd_exit(message: Message) -> None:
    conv = await _ensure_conversation(message)
    if conv is None:
        return
    if conv.active_mode != AGENT_MODE_AGENT:
        await send_plain(message.bot, message.chat.id, "Ты уже в обычном режиме.")
        return
    previous_agent = get_agent_registry().get(conv.active_agent_id)
    activation = build_default_mode_activation()
    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id,
            active_mode=activation.active_mode,
            agent_id=activation.active_agent_id,
            skill_id=activation.active_skill_id,
            model_id=activation.active_model_id,
        )
    await send_plain(
        message.bot,
        message.chat.id,
        (
            f"Ты вышел из режима: {escape_html(previous_agent.name)}. "
            "Теперь отвечает универсальный ассистент."
        ),
    )


@router.callback_query(F.data == "agent:menu")
async def cb_agent_menu(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        conv = await _ensure_conversation(callback.message)
        if conv is not None:
            await callback.message.edit_text(
                _agent_menu_text(conv.active_mode, conv.active_agent_id),
                reply_markup=_agent_menu_keyboard(
                    show_exit=conv.active_mode == AGENT_MODE_AGENT
                ),
            )
    await callback.answer()


@router.callback_query(F.data.in_({"agent:select:crypto", "agent:select:news"}))
async def cb_agent_select(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    agent_id = str(callback.data).rsplit(":", 1)[-1]
    await _activate_agent_mode_for_message(callback.message, agent_id)
    await callback.answer()


@router.callback_query(F.data == "agent:exit")
async def cb_agent_exit(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await cmd_exit(callback.message)
    await callback.answer()


@router.callback_query(F.data == "agent:settings")
async def cb_agent_settings(callback: CallbackQuery) -> None:
    from app.bot.handlers.settings import render_agents_settings_callback

    await render_agents_settings_callback(callback)


@router.callback_query(F.data == "agent:close")
async def cb_agent_close(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("Закрыто.")
        except Exception:  # noqa: BLE001
            log.debug("agent close: edit_text failed", exc_info=True)
    await callback.answer()


@router.callback_query(F.data == "agent:menu")
async def cb_agent_menu(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        conv = await _ensure_conversation(callback.message)
        if conv is not None:
            await callback.message.edit_text(
                _agent_menu_text(conv.active_mode, conv.active_agent_id),
                reply_markup=_agent_menu_keyboard(show_exit=conv.active_mode == AGENT_MODE_AGENT),
            )
    await callback.answer()


@router.callback_query(F.data == "agent:select:crypto")
async def cb_agent_select_crypto(callback: CallbackQuery) -> None:
    await _activate_agent_mode_for_callback(callback, "crypto")


@router.callback_query(F.data == "agent:select:news")
async def cb_agent_select_news(callback: CallbackQuery) -> None:
    await _activate_agent_mode_for_callback(callback, "news")


@router.callback_query(F.data == "agent:exit")
async def cb_agent_exit(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    conv = await _ensure_conversation(callback.message)
    if conv is None:
        await callback.answer()
        return
    if conv.active_mode != AGENT_MODE_AGENT:
        await callback.answer("Ты уже в обычном режиме.", show_alert=True)
        return
    previous_agent = get_agent_registry().get(conv.active_agent_id)
    activation = build_default_mode_activation()
    async with session_scope() as session:
        repo = ConversationRepository(session)
        await repo.update_active_routing(
            conversation_id=conv.id,
            active_mode=activation.active_mode,
            agent_id=activation.active_agent_id,
            skill_id=activation.active_skill_id,
            model_id=activation.active_model_id,
        )
    await callback.message.answer(
        f"Ты вышел из режима: {escape_html(previous_agent.name)}. "
        "Теперь отвечает универсальный ассистент."
    )
    await callback.answer("Обычный режим")


@router.callback_query(F.data == "agent:settings")
async def cb_agent_settings(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "<b>Настройки агентов</b>\n\nОткрой /settings → Агенты для настройки prompt/model агентов."
        )
    await callback.answer()


@router.callback_query(F.data == "agent:close")
async def cb_agent_close(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Закрыто.")
    await callback.answer()


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
    overrides = await get_settings_store().list_model_overrides()
    lines = ["<b>Доступные модели:</b>"]
    for m in models:
        line = (
            f"• <code>{escape_html(m.id)}</code> — <b>{escape_html(m.display_name)}</b> "
            f"({escape_html(m.tier)}, {escape_html(m.provider)}/{escape_html(m.model_name)})"
        )
        override = overrides.get(m.id)
        if override:
            line += f" — <i>override: {escape_html(override)}</i>"
        lines.append(line)
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
