"""Хэндлеры команд: /start, /help, /reset, /status, /history, /agents, /agent,
/skills, /skill, /models, /model.
"""

from __future__ import annotations

import logging
from datetime import timezone
from decimal import Decimal

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.agents.registry import get_agent_registry
from app.bot.renderers.telegram_text import escape_html, send_long_html, send_plain
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
from app.db.repositories.llm_requests import LLMRequestRepository
from app.db.repositories.messages import MessageRepository
from app.db.repositories.users import UserRepository
from app.bot.handlers.portfolio_helpers import parse_add_eth_amount
from app.core.alert_logic import parse_positive_usd_price, resolve_alert_direction
from app.core.price.eth import fetch_eth_usd_price
from app.db.repositories.eth_alerts import EthAlertRepository
from app.utils.formatting import format_decimal
from app.db.session import session_scope
from app.redis.client import ping as redis_ping
from app.models.registry import get_model_registry
from app.skills.registry import get_skill_registry

log = logging.getLogger(__name__)

router = Router(name="commands")

# Все команды-алиасы для skill-ов тоже регистрируем здесь, чтобы они не
# попадали в общий messages-router как обычный текст.
SKILL_COMMAND_ALIASES = (
    "chat",
    "fast",
    "crypto",
    "finance",
    "news",
    "devops",
    "infra",
)
ASK_USAGE = "Использование:\n/ask crypto текст\n/ask news текст"


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


def _activation_for_new_target(target: str, active) -> object:  # noqa: ANN001
    """Выбирает routing state для /new."""
    if target in {"", None}:  # type: ignore[comparison-overlap]
        if getattr(active, "active_mode", AGENT_MODE_DEFAULT) == AGENT_MODE_AGENT:
            agent_id = getattr(active, "active_agent_id", "")
            try:
                return build_agent_mode_activation(agent_id)
            except ValueError:
                return build_default_mode_activation()
        return build_default_mode_activation()
    if target == AGENT_MODE_DEFAULT:
        return build_default_mode_activation()
    if target in available_agent_mode_ids():
        return build_agent_mode_activation(target)
    raise ValueError(target)


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
async def cmd_reset(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    reset_all = (command.args or "").strip().lower() == "all"

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

        if reset_all:
            activation = build_default_mode_activation()
            await conv_repo.archive_active_and_create(
                user_id=user.id,
                chat_id=chat.id,
                active_mode=activation.active_mode,
                active_agent_id=activation.active_agent_id,
                active_skill_id=activation.active_skill_id,
                active_model_id=activation.active_model_id,
            )
            text = "Диалог сброшен. Включён обычный режим."
        else:
            await conv_repo.archive_active_and_create(
                user_id=user.id,
                chat_id=chat.id,
                active_mode=active.active_mode,
                active_agent_id=active.active_agent_id,
                active_skill_id=active.active_skill_id,
                active_model_id=active.active_model_id,
            )
            text = "Диалог сброшен. Текущий режим сохранён."

    await send_plain(message.bot, message.chat.id, text)


@router.message(Command("new"))
async def cmd_new(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return

    target = (command.args or "").strip().lower()
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
        active = await conv_repo.get_or_create_active(user_id=user.id, chat_id=chat.id)
        try:
            activation = _activation_for_new_target(target, active)
        except ValueError:
            await send_plain(
                message.bot,
                message.chat.id,
                "Неизвестный режим. Использование: /new, /new default, /new crypto, /new news.",
            )
            return

        await conv_repo.archive_active_and_create(
            user_id=user.id,
            chat_id=chat.id,
            active_mode=activation.active_mode,
            active_agent_id=activation.active_agent_id,
            active_skill_id=activation.active_skill_id,
            active_model_id=activation.active_model_id,
        )

    await send_plain(
        message.bot,
        message.chat.id,
        (
            f"Создан новый диалог. Режим: <code>{escape_html(activation.active_mode)}</code>, "
            f"агент: <b>{escape_html(activation.agent.name)}</b>."
        ),
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
        "App: ok",
        f"Telegram mode: <code>{escape_html(get_settings().TELEGRAM_MODE)}</code>",
        f"Conversation mode: <code>{escape_html(conv.active_mode)}</code>",
        f"Active agent: <code>{escape_html(agent.id)}</code> — <b>{escape_html(agent.name)}</b>",
        f"Active skill: <code>{escape_html(skill.id)}</code>",
        f"Active model: <code>{escape_html(model.id)}</code>",
        f"Provider: <code>{escape_html(model.provider)}</code>",
        f"Provider model: <code>{escape_html(model.model_name)}</code>",
        f"PostgreSQL: <b>{escape_html(pg_status)}</b>",
        f"Redis: <b>{escape_html(redis_status)}</b>",
        f"Streaming: <b>{'enabled' if model.supports_streaming else 'disabled'}</b>",
        f"Draft: <b>{'enabled' if get_settings().TELEGRAM_STREAM_DRAFT_ENABLED else 'disabled'}</b>",
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


@router.message(Command("debug"))
async def cmd_debug(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    settings = get_settings()
    if message.from_user.id not in settings.admin_telegram_user_ids:
        await send_plain(
            message.bot,
            message.chat.id,
            "Команда доступна только администратору.",
        )
        log.info(
            "debug_access_denied",
            extra={"telegram_user_id": message.from_user.id},
        )
        return

    conv = await _ensure_conversation(message)
    if conv is None:
        return

    pg_status = "unknown"
    redis_status = "unknown"
    try:
        from app.api.diagnostics import _check_postgres, _check_redis

        pg_info = await _check_postgres()
        redis_info = await _check_redis()
        pg_status = "ok" if pg_info.get("ok") else "error"
        redis_status = "ok" if redis_info.get("ok") else "error"
    except Exception:  # noqa: BLE001
        log.exception("Failed to build dependency status for /debug")

    model = get_model_registry().get(conv.active_model_id)
    last_status = "none"
    async with session_scope() as session:
        llm_repo = LLMRequestRepository(session)
        last = await llm_repo.get_last_for_conversation(conversation_id=conv.id)
        if last is not None:
            last_status = last.status

    log.info(
        "debug_command_used",
        extra={
            "telegram_user_id": message.from_user.id,
            "telegram_chat_id": message.chat.id,
            "conversation_id": str(conv.id),
        },
    )
    lines = [
        "<b>Debug</b>",
        "",
        f"telegram_user_id: <code>{message.from_user.id}</code>",
        f"telegram_chat_id: <code>{message.chat.id}</code>",
        f"chat_type: <code>{escape_html(message.chat.type)}</code>",
        f"conversation_id: <code>{escape_html(str(conv.id))}</code>",
        f"active_mode: <code>{escape_html(conv.active_mode)}</code>",
        f"active_agent_id: <code>{escape_html(conv.active_agent_id)}</code>",
        f"active_skill_id: <code>{escape_html(conv.active_skill_id)}</code>",
        f"active_model_id: <code>{escape_html(conv.active_model_id)}</code>",
        f"last_llm_request_status: <code>{escape_html(last_status)}</code>",
        f"provider: <code>{escape_html(model.provider)}</code>",
        f"provider_model_name: <code>{escape_html(model.model_name)}</code>",
        f"Redis: <code>{escape_html(redis_status)}</code>",
        f"PostgreSQL: <code>{escape_html(pg_status)}</code>",
        f"app_env: <code>{escape_html(settings.APP_ENV)}</code>",
        f"telegram_mode: <code>{escape_html(settings.TELEGRAM_MODE)}</code>",
    ]
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
        [InlineKeyboardButton(text="₿ Криптовалютный аналитик", callback_data="agent:select:crypto")],
        [InlineKeyboardButton(text="📰 Новостной агент", callback_data="agent:select:news")],
    ]
    if show_exit:
        rows.append([InlineKeyboardButton(text="🚪 Выйти в обычный режим", callback_data="agent:exit")])
    rows.extend(
        [
            [InlineKeyboardButton(text="⚙️ Настройки агентов", callback_data="agent:settings")],
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
        "Выбери специализированного агента.",
        "После выбора все следующие сообщения будут обрабатываться этим агентом.",
        "Для выхода используй /exit.",
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
            active_mode=activation.active_mode,
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
    await callback.message.answer(
        _agent_enabled_text(activation.agent.name),
        reply_markup=_agent_active_keyboard(),
    )
    await callback.answer("Режим включён")


def _agent_enabled_text(agent_name: str) -> str:
    return (
        f"Режим включён: {escape_html(agent_name)}.\n\n"
        "Теперь все сообщения будут обрабатываться этим агентом.\n\n"
        "Чтобы выйти, используй /exit."
    )


def _agent_active_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настройки агента", callback_data="agent:settings")],
            [InlineKeyboardButton(text="🚪 Выйти из режима", callback_data="agent:exit")],
            [InlineKeyboardButton(text="🔄 Сменить агента", callback_data="agent:menu")],
        ]
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


def _parse_ask_args(args: str) -> tuple[str | None, str]:
    cleaned = (args or "").strip()
    if not cleaned:
        return None, ""
    agent_id, _, question = cleaned.partition(" ")
    return agent_id.lower(), question.strip()


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject) -> None:
    agent_id, question = _parse_ask_args(command.args or "")
    if not agent_id:
        await send_plain(message.bot, message.chat.id, ASK_USAGE)
        return
    if agent_id not in available_agent_mode_ids():
        ids = ", ".join(available_agent_mode_ids()) or "нет доступных спецагентов"
        await send_plain(
            message.bot,
            message.chat.id,
            f"Такой агент не найден.\n\nДоступные агенты: <code>{escape_html(ids)}</code>.",
        )
        return
    if not question:
        await send_plain(
            message.bot,
            message.chat.id,
            "Напиши вопрос после agent id.\n\n" + ASK_USAGE,
        )
        return

    log.info(
        "one_shot_ask_used",
        extra={
            "telegram_user_id": message.from_user.id if message.from_user else None,
            "agent_id": agent_id,
        },
    )
    from app.bot.handlers.messages import process_user_message

    await process_user_message(
        message,
        override_text=question,
        one_shot_agent_id=agent_id,
    )


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
    from app.bot.handlers.settings import render_agents_settings_callback

    await render_agents_settings_callback(callback)


@router.callback_query(F.data == "agent:close")
async def cb_agent_close(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Меню закрыто.")
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


# ---------------------------------------------------------------------------
# Stage 4: portfolio, alerts, digest
# ---------------------------------------------------------------------------


@router.message(Command("portfolio"))
async def cmd_portfolio(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    async with session_scope() as session:
        user_repo = UserRepository(session)
        u = await user_repo.get_by_telegram_id(message.from_user.id)

        bal = Decimal(u.eth_balance) if u else Decimal(0)
    import httpx

    price = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as hc:
        price = await fetch_eth_usd_price(client=hc)
    lines = [
        "<b>Портфель (ручной учёт)</b>",
        f"ETH: <b>{format_decimal(bal)}</b>",
    ]
    if price is not None:
        lines.append(f"Цена ETH (CoinGecko): ~<b>{format_decimal(price)}</b> USD")
        lines.append(
            f"Оценка в USD: ~<b>{format_decimal(bal * price)}</b> "
            "(индикативно, не инвестсовет)."
        )
    else:
        lines.append("Цена ETH сейчас недоступна (CoinGecko).")
    await send_plain(message.bot, message.chat.id, "\n".join(lines))


@router.message(Command("add_eth"))
async def cmd_add_eth(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    amount, err = parse_add_eth_amount(command.args)
    if err:
        await send_plain(message.bot, message.chat.id, err)
        return
    async with session_scope() as session:
        user_repo = UserRepository(session)
        await user_repo.add_eth_balance(
            telegram_user_id=message.from_user.id, delta=amount
        )
    await send_plain(
        message.bot,
        message.chat.id,
        f"Баланс увеличен на <b>{format_decimal(amount)}</b> ETH. См. /portfolio.",
    )


@router.message(Command("alert_eth"))
async def cmd_alert_eth(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    target, err = parse_positive_usd_price(command.args)
    if err:
        await send_plain(message.bot, message.chat.id, err)
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as hc:
        current = await fetch_eth_usd_price(client=hc)
    if current is None:
        await send_plain(
            message.bot,
            message.chat.id,
            "Текущая цена ETH недоступна (CoinGecko). Алерт не создан.",
        )
        return
    direction, derr = resolve_alert_direction(target=target, current=current)
    if derr:
        await send_plain(message.bot, message.chat.id, derr)
        return
    async with session_scope() as session:
        user_repo = UserRepository(session)
        u = await user_repo.get_by_telegram_id(message.from_user.id)
        if u is None:
            return
        ar = EthAlertRepository(session)
        await ar.create(user_id=u.id, target_price_usd=target, direction=direction)
    await send_plain(
        message.bot,
        message.chat.id,
        (
            f"Алерт создан: цель <b>{format_decimal(target)}</b> USD, "
            f"сейчас ~<b>{format_decimal(current)}</b> USD, направление: <b>{direction}</b>."
        ),
    )


@router.message(Command("alerts"))
async def cmd_alerts(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    async with session_scope() as session:
        user_repo = UserRepository(session)
        u = await user_repo.get_by_telegram_id(message.from_user.id)
        if u is None:
            return
        ar = EthAlertRepository(session)
        rows = await ar.list_active_for_user(user_id=u.id)
    if not rows:
        await send_plain(message.bot, message.chat.id, "Активных ETH-алертов нет.")
        return
    lines = ["<b>Активные ETH-алерты:</b>"]
    for r in rows:
        lines.append(
            f"• цель <b>{format_decimal(r.target_price_usd)}</b> USD, "
            f"направление <code>{escape_html(r.direction)}</code>"
        )
    await send_plain(message.bot, message.chat.id, "\n".join(lines))


@router.message(Command("alert_cancel"))
async def cmd_alert_cancel(message: Message, command: CommandObject) -> None:
    if message.from_user is None or message.chat is None:
        return
    args = (command.args or "").strip().lower()
    if args != "all":
        await send_plain(
            message.bot,
            message.chat.id,
            "Использование: /alert_cancel all",
        )
        return
    await _ensure_conversation(message)
    async with session_scope() as session:
        user_repo = UserRepository(session)
        u = await user_repo.get_by_telegram_id(message.from_user.id)
        if u is None:
            return
        ar = EthAlertRepository(session)
        n = await ar.deactivate_all_for_user(user_id=u.id)
    await send_plain(
        message.bot,
        message.chat.id,
        f"Деактивировано алертов: <b>{n}</b>.",
    )


@router.message(Command("digest_on"))
async def cmd_digest_on(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    async with session_scope() as session:
        user_repo = UserRepository(session)
        await user_repo.set_digest_enabled(
            telegram_user_id=message.from_user.id, enabled=True
        )
    await send_plain(message.bot, message.chat.id, "Ежедневный digest включён.")


@router.message(Command("digest_off"))
async def cmd_digest_off(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    async with session_scope() as session:
        user_repo = UserRepository(session)
        await user_repo.set_digest_enabled(
            telegram_user_id=message.from_user.id, enabled=False
        )
    await send_plain(message.bot, message.chat.id, "Ежедневный digest выключен.")


@router.message(Command("digest_status"))
async def cmd_digest_status(message: Message) -> None:
    if message.from_user is None or message.chat is None:
        return
    await _ensure_conversation(message)
    settings = get_settings()
    async with session_scope() as session:
        user_repo = UserRepository(session)
        u = await user_repo.get_by_telegram_id(message.from_user.id)
        enabled = bool(u.digest_enabled) if u else False
        last = u.last_digest_sent_at if u else None
    last_s = "—"
    if last is not None:
        last_s = last.astimezone(timezone.utc).isoformat()
    lines = [
        "<b>Digest</b>",
        f"Включён: <b>{'да' if enabled else 'нет'}</b>",
        f"DAILY_DIGEST_HOUR_UTC: <code>{settings.DAILY_DIGEST_HOUR_UTC}</code>",
        f"last_digest_sent_at: <code>{escape_html(last_s)}</code>",
    ]
    await send_plain(message.bot, message.chat.id, "\n".join(lines))


__all__ = ["router"]
