"""Хэндлер обычных текстовых сообщений: основной поток LLM-обработки."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.agents.registry import get_agent_registry
from app.bot.renderers.telegram_stream_renderer import TelegramStreamRenderer
from app.bot.renderers.telegram_text import send_plain
from app.core.context_builder import ContextBuilder
from app.core.idempotency import is_first_seen
from app.core.orchestrator import Orchestrator
from app.core.prompts import (
    EMPTY_LLM_RESPONSE,
    LLM_GENERIC_ERROR,
    OPENROUTER_NOT_CONFIGURED,
    RATE_LIMIT_MESSAGE,
)
from app.core.rate_limit import RateLimiter
from app.core.settings_store import get_settings_store
from app.db.models import (
    MESSAGE_DIRECTION_INBOUND,
    MESSAGE_DIRECTION_OUTBOUND,
    MESSAGE_TYPE_TEXT,
)
from app.db.repositories.chats import ChatRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.repositories.llm_requests import LLMRequestRepository
from app.db.repositories.messages import MessageRepository
from app.db.repositories.users import UserRepository
from app.db.session import session_scope
from app.llm.openrouter_client import (
    OpenRouterAuthError,
    OpenRouterError,
    get_openrouter_client,
)
from app.skills.registry import get_skill_registry
from app.skills.router import SkillResolution, SkillRouter

log = logging.getLogger(__name__)

router = Router(name="messages")


async def process_user_message(
    message: Message,
    *,
    override_text: str | None = None,
) -> None:
    """Главный pipeline обработки сообщения.

    override_text используется, когда команда-алиас (/crypto Текст) уже
    переключила skill, а сам текст надо обработать как обычное сообщение.
    """
    if message.from_user is None or message.chat is None:
        return

    text = override_text if override_text is not None else (message.text or "")
    text = text.strip()
    if not text:
        return

    # 1) Идемпотентность апдейтов.
    update_id = getattr(message, "_telegram_update_id", None)
    # message.update_id отсутствует у Message — это поле есть у Update.
    # В aiogram доступ к update_id есть через middleware/event; чтобы не
    # тащить его сюда, обернём идемпотентность по telegram_message_id чата.
    # message_id уникален в пределах чата, но не глобально — в processed_updates
    # используется отдельная константа для "псевдо-update_id".
    if update_id is None:
        # Telegram message_id < 2^53; объединим с chat_id, оставаясь в BigInteger.
        update_id = abs(hash((message.chat.id, message.message_id))) & 0x7FFFFFFFFFFFFFFF

    try:
        is_new = await is_first_seen(int(update_id))
    except Exception:  # noqa: BLE001
        log.exception("Idempotency check failed; proceeding")
        is_new = True

    if not is_new:
        log.info(
            "Skipping duplicate update", extra={"chat_id": message.chat.id, "message_id": message.message_id}
        )
        return

    # 2) Rate limit.
    limiter = RateLimiter()
    decision = await limiter.check(message.from_user.id)
    if not decision.allowed:
        await send_plain(message.bot, message.chat.id, RATE_LIMIT_MESSAGE)
        return

    # 3) Upsert user/chat/conversation.
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
        conversation = await conv_repo.get_or_create_active(
            user_id=user.id, chat_id=chat.id
        )
        conversation_id = conversation.id
        active_skill_id = conversation.active_skill_id

    # 4) Skill routing (по тексту + активному skill).
    skill_router = SkillRouter()
    resolution: SkillResolution = skill_router.resolve(
        text=text, active_skill_id=active_skill_id
    )
    skill = resolution.skill
    user_text = resolution.cleaned_text or text  # если команда без аргументов — оставим исходный текст

    # 5) Агент и план модели.
    agent_registry = get_agent_registry()
    agent = agent_registry.get(skill.agent_id)

    # Если skill пришёл по команде — обновим conversation.active_*.
    if resolution.matched_by == "command":
        async with session_scope() as session:
            conv_repo = ConversationRepository(session)
            await conv_repo.update_active_routing(
                conversation_id=conversation_id,
                agent_id=agent.id,
                skill_id=skill.id,
                model_id=skill.model_id or agent.default_model_id,
            )

        # Если команда пришла без аргументов — просто переключаем и отвечаем.
        if not user_text or user_text.startswith("/"):
            await send_plain(
                message.bot,
                message.chat.id,
                (
                    f"Активный навык изменён: <b>{skill.name}</b>. "
                    f"Теперь сообщения будут обрабатываться через агента: "
                    f"<b>{agent.name}</b>."
                ),
            )
            return

    # 6) Если OpenRouter не настроен — отвечаем заглушкой.
    # Учитываем как ENV, так и БД-override (admin /settings).
    or_client = get_openrouter_client()
    effective_api_key = await get_settings_store().get_openrouter_api_key()
    if not effective_api_key:
        await send_plain(message.bot, message.chat.id, OPENROUTER_NOT_CONFIGURED)
        return

    # 7) Сохраняем inbound, готовим контекст, стартуем рендерер.
    async with session_scope() as session:
        msg_repo = MessageRepository(session)
        await msg_repo.add(
            conversation_id=conversation_id,
            direction=MESSAGE_DIRECTION_INBOUND,
            text=user_text,
            telegram_message_id=message.message_id,
            message_type=MESSAGE_TYPE_TEXT,
        )

    orchestrator = Orchestrator(client=or_client)
    plan = await orchestrator.plan_async(
        agent=agent,
        skill=skill,
        explicit_model_id=None,  # активная модель из conversation учитывается через update_active_routing
    )

    async with session_scope() as session:
        cb = ContextBuilder(session)
        # Перечитаем conversation, чтобы получить свежее состояние active_*.
        conv_repo = ConversationRepository(session)
        conversation = await conv_repo.get_or_create_active(
            user_id=user.id, chat_id=chat.id
        )
        agent = await cb.resolve_agent(conversation)
        # План мог зависеть от другого агента — перестроим под актуальный.
        plan = await orchestrator.plan_async(agent=agent, skill=skill)
        messages_payload = await cb.build_messages(
            conversation=conversation, agent=agent
        )

    # 8) Стартуем LLM-стрим и рендерим в Telegram.
    renderer = TelegramStreamRenderer(
        message.bot,
        chat_id=message.chat.id,
        chat_type=message.chat.type,
    )
    await renderer.start()

    request_id = None
    async with session_scope() as session:
        llm_repo = LLMRequestRepository(session)
        request = await llm_repo.create_started(
            conversation_id=conversation_id,
            agent_id=agent.id,
            skill_id=skill.id,
            model_id=plan.model.id,
            provider=plan.model.provider,
            provider_model_name=plan.model.model_name,
        )
        request_id = request.id

    final_text = ""
    error_text: str | None = None
    error_text_for_db: str | None = None
    try:
        async for chunk in orchestrator.run(plan=plan, messages=messages_payload):
            if chunk.content_delta:
                await renderer.push(chunk.content_delta)
            if chunk.finish_reason:
                break
        result = await renderer.finalize()
        final_text = result.final_text
    except OpenRouterAuthError as exc:
        log.warning("OpenRouter auth error during streaming")
        error_text = OPENROUTER_NOT_CONFIGURED
        error_text_for_db = repr(exc)[:500]
    except OpenRouterError as exc:
        log.warning("OpenRouter error: %s", exc.__class__.__name__)
        error_text = LLM_GENERIC_ERROR
        error_text_for_db = repr(exc)[:500]
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected error in LLM streaming pipeline")
        error_text = LLM_GENERIC_ERROR
        # Полный repr (вместе с типом и сообщением) — для post-mortem в БД,
        # пользователю по-прежнему отдаём дружелюбный LLM_GENERIC_ERROR.
        error_text_for_db = repr(exc)[:500]

    # 9) Если стрим был пустой — отвечаем фолбэком.
    if not final_text and error_text is None:
        error_text = EMPTY_LLM_RESPONSE

    if error_text is not None:
        await send_plain(message.bot, message.chat.id, error_text)
        async with session_scope() as session:
            llm_repo = LLMRequestRepository(session)
            await llm_repo.mark_error(
                request_id=request_id,
                error=error_text_for_db or error_text,
            )
        return

    # 10) Успех: пишем outbound и помечаем llm_request успешным.
    async with session_scope() as session:
        msg_repo = MessageRepository(session)
        llm_repo = LLMRequestRepository(session)
        await msg_repo.add(
            conversation_id=conversation_id,
            direction=MESSAGE_DIRECTION_OUTBOUND,
            text=final_text,
            telegram_message_id=None,
            message_type=MESSAGE_TYPE_TEXT,
        )
        await llm_repo.mark_success(request_id=request_id)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: Message) -> None:
    await process_user_message(message)


__all__ = ["router", "process_user_message"]
