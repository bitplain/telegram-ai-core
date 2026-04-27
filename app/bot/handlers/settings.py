"""Admin /settings: API settings and per-user agent settings."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters.admin import AdminFilter
from app.config import get_settings
from app.core.services.user_agent_settings import (
    AgentPromptTooLongError,
    EmptyAgentPromptError,
    UnknownAgentError,
    UnknownModelError,
    UserAgentSettingsService,
)
from app.core.settings_store import get_settings_store
from app.llm.openrouter_models import ModelInfo, get_openrouter_models_client
from app.models.registry import get_model_registry

log = logging.getLogger(__name__)

settings_router = Router(name="settings")

_PAGE_SIZE = 8
_PROMPT_PREVIEW_CHARS = 500


class SettingsStates(StatesGroup):
    awaiting_yandex_api_key = State()
    awaiting_agent_prompt = State()
    browsing_favorites = State()


class SettingsCB(CallbackData, prefix="s"):
    action: str
    arg1: str = ""
    arg2: str = ""


def _looks_like_settings_command(text: str | None) -> bool:
    if not text:
        return False
    cmd = text.strip().split(maxsplit=1)[0].lower()
    if not cmd.startswith("/settings"):
        return False
    return cmd == "/settings" or cmd.startswith("/settings@")


def _looks_like_cancel_command(text: str | None) -> bool:
    if not text:
        return False
    cmd = text.strip().split(maxsplit=1)[0].lower()
    if not cmd.startswith("/cancel"):
        return False
    return cmd == "/cancel" or cmd.startswith("/cancel@")


def _is_admin_message(message: Message) -> bool:
    if message.from_user is None:
        return False
    return message.from_user.id in get_settings().admin_telegram_user_ids


async def _answer_settings_access_denied(message: Message) -> None:
    await message.answer(
        "Команда /settings доступна только администраторам.\n"
        "Проверьте, что ваш Telegram user id добавлен в "
        "<code>ADMIN_TELEGRAM_IDS</code>."
    )


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:7]}...{value[-4:]}"


def _format_price(price: float | None) -> str:
    if price is None:
        return "?"
    return f"${price * 1_000_000:.2f}/1M"


def _model_label(model) -> str:  # noqa: ANN001
    """Показываем пользователю реальный OpenRouter slug, а не внутренний id."""
    return str(getattr(model, "model_name", None) or getattr(model, "id", ""))


def _preview_text(value: str, *, limit: int = _PROMPT_PREVIEW_CHARS) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="API", callback_data=SettingsCB(action="api").pack())],
            [InlineKeyboardButton(text="Агенты", callback_data=SettingsCB(action="agents").pack())],
            [InlineKeyboardButton(text="Закрыть", callback_data=SettingsCB(action="close").pack())],
        ]
    )


def _api_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить API", callback_data=SettingsCB(action="providers").pack())],
            [InlineKeyboardButton(text="Сбросить настройки моделей", callback_data=SettingsCB(action="reset").pack())],
            [InlineKeyboardButton(text="Назад в настройки", callback_data=SettingsCB(action="main").pack())],
        ]
    )


def _providers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="OpenRouter", callback_data=SettingsCB(action="provider", arg1="openrouter").pack())],
            [InlineKeyboardButton(text="Яндекс", callback_data=SettingsCB(action="provider", arg1="yandex").pack())],
            [InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="api").pack())],
        ]
    )


def _openrouter_keyboard(*, openrouter_configured: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if openrouter_configured:
        rows.append(
            [InlineKeyboardButton(text="Избранное", callback_data=SettingsCB(action="favorites").pack())]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Обновить список моделей",
                    callback_data=SettingsCB(action="refresh").pack(),
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="providers").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _yandex_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="+ API", callback_data=SettingsCB(action="yandex_add_api").pack())],
            [InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="providers").pack())],
        ]
    )


def _agents_keyboard(service: UserAgentSettingsService | None = None) -> InlineKeyboardMarkup:
    service = service or UserAgentSettingsService()
    rows = [
        [InlineKeyboardButton(text=agent.name, callback_data=SettingsCB(action="agent", arg1=agent.id).pack())]
        for agent in service.list_enabled_agents()
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="main").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _agent_keyboard(agent_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить prompt", callback_data=SettingsCB(action="agent_prompt", arg1=agent_id).pack())],
            [InlineKeyboardButton(text="Выбрать модель", callback_data=SettingsCB(action="agent_models", arg1=agent_id).pack())],
            [InlineKeyboardButton(text="Сбросить prompt", callback_data=SettingsCB(action="agent_reset", arg1=agent_id).pack())],
            [InlineKeyboardButton(text="Назад к агентам", callback_data=SettingsCB(action="agents").pack())],
            [InlineKeyboardButton(text="Назад в настройки", callback_data=SettingsCB(action="main").pack())],
        ]
    )


def _agent_models_keyboard(agent_id: str, favorite_slugs: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=slug[:64],
                callback_data=SettingsCB(action="agent_set_model", arg1=agent_id, arg2=slug).pack(),
            )
        ]
        for slug in favorite_slugs
    ]
    if not rows:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Избранное пусто",
                    callback_data=SettingsCB(action="noop").pack(),
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="agent", arg1=agent_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _models_page_keyboard(
    *,
    page: int,
    total_pages: int,
    page_models: list[ModelInfo],
    favorite_slugs: set[str] | None = None,
) -> InlineKeyboardMarkup:
    favorite_slugs = favorite_slugs or set()
    rows: list[list[InlineKeyboardButton]] = []
    for idx, model in enumerate(page_models):
        mark = "✓ " if model.id in favorite_slugs else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{model.id}"[:64], callback_data=SettingsCB(action="fav_pick", arg1=str(page), arg2=str(idx)).pack())])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="‹", callback_data=SettingsCB(action="page", arg1=str(page - 1)).pack()))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=SettingsCB(action="noop").pack()))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="›", callback_data=SettingsCB(action="page", arg1=str(page + 1)).pack()))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="provider", arg1="openrouter").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _settings_status_text() -> str:
    store = get_settings_store()
    cfg = get_settings()
    openrouter_api_key = (cfg.OPENROUTER_API_KEY or "").strip()
    yandex_api_key = await store.get_yandex_api_key()
    has_db_yandex_key = await store.has_db_yandex_api_key()

    openrouter_src = "ENV" if openrouter_api_key else "не задан"
    yandex_src = "БД" if has_db_yandex_key else "не задан"
    openrouter_line = f"OpenRouter: <b>{openrouter_src}</b>" + (
        f" ({_mask_key(openrouter_api_key)})" if openrouter_api_key else ""
    )
    yandex_line = f"Yandex: <b>{yandex_src}</b>" + (
        f" ({_mask_key(yandex_api_key or '')})" if yandex_api_key else ""
    )
    return (
        f"{openrouter_line}\n"
        f"{yandex_line}\n"
        f"Шифрование БД: <b>{'включено' if store.encryption_enabled else 'выключено (plaintext)'}</b>"
    )


async def _render_main_to_message(message: Message) -> None:
    await message.answer("<b>Настройки</b>\n\nВыберите раздел:", reply_markup=_main_keyboard())


async def _edit_or_answer(message: Message, text: str, keyboard: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:  # noqa: BLE001
        await message.answer(text, reply_markup=keyboard)


async def _render_main_callback(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, "<b>Настройки</b>\n\nВыберите раздел:", _main_keyboard())


async def _render_api_menu(message: Message) -> None:
    text = "<b>Настройки API</b>\n\n" + await _settings_status_text()
    await _edit_or_answer(message, text, _api_keyboard())


async def _render_provider_menu(message: Message) -> None:
    await _edit_or_answer(message, "<b>API</b>\n\nВыберите провайдера:", _providers_keyboard())


async def _render_openrouter_menu(message: Message) -> None:
    cfg = get_settings()
    api_key = (cfg.OPENROUTER_API_KEY or "").strip()
    has_key = bool(api_key)
    body = ["<b>OpenRouter</b>"]
    body.append(
        f"Ключ: <b>ENV</b> ({_mask_key(api_key)})" if has_key else "Ключ: <b>не задан</b> в переменных окружения"
    )
    body.append(
        "API-ключ задаётся только через <code>OPENROUTER_API_KEY</code> в окружении "
        "(Railway Variables / docker-compose). Здесь доступны избранные модели и overrides."
    )
    await _edit_or_answer(
        message,
        "\n\n".join(body),
        _openrouter_keyboard(openrouter_configured=has_key),
    )


async def _render_yandex_menu(message: Message) -> None:
    store = get_settings_store()
    api_key = await store.get_yandex_api_key()
    source = "БД" if await store.has_db_yandex_api_key() else "не задан"
    body = ["<b>Яндекс (заглушка)</b>"]
    body.append(f"Ключ: <b>{source}</b> ({_mask_key(api_key)})" if api_key else "Ключ: <b>не задан</b>")
    body.append("Провайдер пока не подключен к runtime. + API сохраняет ключ в настройки.")
    await _edit_or_answer(message, "\n\n".join(body), _yandex_keyboard())


async def _render_agents_menu(message: Message) -> None:
    await _edit_or_answer(message, "<b>Настройки агентов</b>\n\nВыберите агента:", _agents_keyboard())


async def render_agents_settings_callback(callback: CallbackQuery) -> None:
    """Переход из внешних inline-меню в существующий раздел /settings → Агенты."""
    if isinstance(callback.message, Message):
        await _render_agents_menu(callback.message)
    await callback.answer()


async def _render_agent_menu(message: Message, *, telegram_user_id: int, agent_id: str) -> None:
    service = UserAgentSettingsService()
    try:
        settings = await service.get_effective_settings(telegram_user_id=telegram_user_id, agent_id=agent_id)
    except UnknownAgentError:
        await _edit_or_answer(message, "Агент не найден.", _agents_keyboard(service))
        return

    agent = settings.agent
    model_source = "пользовательская" if settings.selected_model else "по умолчанию"
    if settings.custom_prompt:
        prompt_line = "пользовательский"
        prompt_preview = _preview_text(settings.custom_prompt)
    else:
        prompt_line = "по умолчанию"
        prompt_preview = _preview_text(settings.default_prompt)

    text = (
        f"<b>Агент: {agent.name}</b>\n"
        f"ID: <code>{agent.id}</code>\n"
        f"Модель: <code>{_model_label(settings.effective_model)}</code> ({model_source})\n"
        f"Описание: {agent.description or 'не задано'}\n"
        f"Prompt: <b>{prompt_line}</b>\n\n"
        f"<code>{prompt_preview}</code>"
    )
    await _edit_or_answer(message, text, _agent_keyboard(agent.id))


@settings_router.message(F.text.func(_looks_like_settings_command))
async def cmd_settings_entrypoint(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not _is_admin_message(message):
        await _answer_settings_access_denied(message)
        return
    await _render_main_to_message(message)


@settings_router.callback_query(SettingsCB.filter(F.action == "main"), AdminFilter())
async def cb_main(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    await _render_main_callback(callback)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "api"), AdminFilter())
async def cb_api(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await _render_api_menu(callback.message)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "agents"), AdminFilter())
async def cb_agents(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await _render_agents_menu(callback.message)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "agent"), AdminFilter())
async def cb_agent(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await _render_agent_menu(callback.message, telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "agent_prompt"), AdminFilter())
async def cb_agent_prompt(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    service = UserAgentSettingsService()
    try:
        settings = await service.get_effective_settings(telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1)
    except UnknownAgentError:
        await callback.answer("Агент не найден", show_alert=True)
        return
    await state.set_state(SettingsStates.awaiting_agent_prompt)
    await state.update_data(agent_id=settings.agent.id)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"Отправьте новый prompt для агента <b>{settings.agent.name}</b>.\n"
            f"Максимальная длина: {get_settings().AGENT_PROMPT_MAX_LENGTH} символов.\n"
            "Отмена: /cancel"
        )
    await callback.answer()


@settings_router.message(SettingsStates.awaiting_agent_prompt, AdminFilter())
async def on_agent_prompt_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    agent_id = str(data.get("agent_id") or "")
    raw = (message.text or "").strip()
    if not agent_id:
        await state.clear()
        await message.answer("Сессия истекла. Откройте /settings заново.")
        return
    service = UserAgentSettingsService()
    try:
        await service.set_custom_prompt(telegram_user_id=message.from_user.id, agent_id=agent_id, custom_prompt=raw)  # type: ignore[union-attr]
    except EmptyAgentPromptError:
        await message.answer("Prompt пустой. Отправьте непустой текст или /cancel.")
        return
    except AgentPromptTooLongError:
        await message.answer(f"Prompt слишком длинный. Максимум: {get_settings().AGENT_PROMPT_MAX_LENGTH} символов.")
        return
    except UnknownAgentError:
        await state.clear()
        await message.answer("Агент не найден. Откройте /settings заново.")
        return
    await state.clear()
    settings = await service.get_effective_settings(telegram_user_id=message.from_user.id, agent_id=agent_id)  # type: ignore[union-attr]
    await message.answer(f"Prompt для агента <b>{settings.agent.name}</b> сохранён.")
    await _render_agent_menu(message, telegram_user_id=message.from_user.id, agent_id=agent_id)  # type: ignore[union-attr]


@settings_router.callback_query(SettingsCB.filter(F.action == "agent_reset"), AdminFilter())
async def cb_agent_reset(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    service = UserAgentSettingsService()
    try:
        await service.reset_custom_prompt(telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1)
        settings = await service.get_effective_settings(telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1)
    except UnknownAgentError:
        await callback.answer("Агент не найден", show_alert=True)
        return
    if isinstance(callback.message, Message):
        await callback.message.answer(f"Prompt для агента <b>{settings.agent.name}</b> сброшен. Используется prompt по умолчанию.")
        await _render_agent_menu(callback.message, telegram_user_id=callback.from_user.id, agent_id=settings.agent.id)
    await callback.answer("Сброшено")


@settings_router.callback_query(SettingsCB.filter(F.action == "agent_models"), AdminFilter())
async def cb_agent_models(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    service = UserAgentSettingsService()
    try:
        settings = await service.get_effective_settings(telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1)
    except UnknownAgentError:
        await callback.answer("Агент не найден", show_alert=True)
        return
    favorite_slugs = await service.list_favorite_model_slugs()
    if isinstance(callback.message, Message):
        text = f"<b>Выберите модель для агента {settings.agent.name}</b>:"
        if not favorite_slugs:
            text += "\n\nИзбранное пусто. Добавьте модели: /settings → API → OpenRouter → Избранное."
        await _edit_or_answer(
            callback.message,
            text,
            _agent_models_keyboard(settings.agent.id, favorite_slugs),
        )
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "agent_set_model"), AdminFilter())
async def cb_agent_set_model(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    service = UserAgentSettingsService()
    try:
        await service.set_model_id(telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1, model_id=callback_data.arg2)
        settings = await service.get_effective_settings(telegram_user_id=callback.from_user.id, agent_id=callback_data.arg1)
    except UnknownAgentError:
        await callback.answer("Агент не найден", show_alert=True)
        return
    except UnknownModelError:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    if isinstance(callback.message, Message):
        await callback.message.answer(f"Модель для агента <b>{settings.agent.name}</b> сохранена: <code>{_model_label(settings.effective_model)}</code>")
        await _render_agent_menu(callback.message, telegram_user_id=callback.from_user.id, agent_id=settings.agent.id)
    await callback.answer("Сохранено")


@settings_router.callback_query(SettingsCB.filter(F.action == "providers"), AdminFilter())
async def cb_providers(callback: CallbackQuery, callback_data: SettingsCB) -> None:
    if isinstance(callback.message, Message):
        await _render_provider_menu(callback.message)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "provider"), AdminFilter())
async def cb_provider(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        if callback_data.arg1 == "openrouter":
            await _render_openrouter_menu(callback.message)
        elif callback_data.arg1 == "yandex":
            await _render_yandex_menu(callback.message)
        else:
            await _render_provider_menu(callback.message)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "noop"), AdminFilter())
async def cb_noop(callback: CallbackQuery, callback_data: SettingsCB) -> None:
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "close"), AdminFilter())
async def cb_close(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("Закрыто.")
        except Exception:  # noqa: BLE001
            log.debug("close: edit_text failed", exc_info=True)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "yandex_add_api"), AdminFilter())
async def cb_yandex_add_api(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.set_state(SettingsStates.awaiting_yandex_api_key)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отправьте Yandex API key одним сообщением.\n"
            "Это заглушка: ключ сохранится, но пока не используется в runtime."
        )
    await callback.answer()


@settings_router.message(SettingsStates.awaiting_yandex_api_key, AdminFilter())
async def on_yandex_api_key_message(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение. Отправьте ключ ещё раз или /cancel.")
        return
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        log.debug("Could not delete user message with Yandex API key", exc_info=True)
    if message.from_user is None:
        await state.clear()
        return
    store = get_settings_store()
    await store.set_yandex_api_key(raw, by_user_id=message.from_user.id)
    await state.clear()
    await message.answer("Yandex API key сохранён как заглушка. Интеграция провайдера пока не подключена.", reply_markup=_yandex_keyboard())


@settings_router.message(Command("cancel"), AdminFilter())
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Отменять нечего.")
        return
    await state.clear()
    await message.answer("Отменено.", reply_markup=_main_keyboard())


@settings_router.callback_query(SettingsCB.filter(F.action == "reset"), AdminFilter())
async def cb_reset(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    store = get_settings_store()
    await store.reset_all_overrides()
    if isinstance(callback.message, Message):
        await _edit_or_answer(
            callback.message,
            "Все model overrides удалены. OpenRouter ключ в ENV не меняется.",
            _api_keyboard(),
        )
    await callback.answer("Готово")


@settings_router.callback_query(SettingsCB.filter(F.action == "refresh"), AdminFilter())
async def cb_refresh(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    models = await get_openrouter_models_client().fetch(force=True)
    text = f"Список моделей обновлён. Доступно: <b>{len(models)}</b>."
    if isinstance(callback.message, Message):
        or_ok = bool((get_settings().OPENROUTER_API_KEY or "").strip())
        await _edit_or_answer(
            callback.message,
            text,
            _openrouter_keyboard(openrouter_configured=or_ok),
        )
    await callback.answer("Готово")


@settings_router.callback_query(SettingsCB.filter(F.action == "favorites"), AdminFilter())
async def cb_favorites(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.set_state(SettingsStates.browsing_favorites)
    models = await get_openrouter_models_client().fetch(force=False)
    if not models:
        await callback.answer("Список моделей пуст. Сначала обновите список моделей.", show_alert=True)
        return
    await state.update_data(
        models=[
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "context_length": m.context_length,
                "pricing_prompt": m.pricing_prompt,
                "pricing_completion": m.pricing_completion,
            }
            for m in models
        ]
    )
    await _render_models_page(callback, state, page=0)


@settings_router.callback_query(SettingsCB.filter(F.action == "page"), AdminFilter())
async def cb_page(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    try:
        page = int(callback_data.arg1)
    except ValueError:
        await callback.answer()
        return
    await _render_models_page(callback, state, page=page)


async def _render_models_page(callback: CallbackQuery, state: FSMContext, *, page: int) -> None:
    data = await state.get_data()
    models_data = data.get("models") or []
    if not models_data:
        await callback.answer("Сессия истекла, откройте /settings заново.", show_alert=True)
        return
    store = get_settings_store()
    favorites = set(await store.list_openrouter_favorite_models())
    total = len(models_data)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * _PAGE_SIZE
    chunk = models_data[start : start + _PAGE_SIZE]
    page_models = [
        ModelInfo(
            id=m["id"],
            name=m["name"],
            provider=m["provider"],
            context_length=m.get("context_length"),
            pricing_prompt=m.get("pricing_prompt"),
            pricing_completion=m.get("pricing_completion"),
        )
        for m in chunk
    ]
    lines = ["<b>Избранные модели OpenRouter</b>", "", "Нажмите модель, чтобы добавить/убрать её из избранного.", ""]
    for idx, model in enumerate(page_models):
        mark = "✓" if model.id in favorites else " "
        lines.append(f"{idx + 1}. {mark} <code>{model.id}</code> — prompt {_format_price(model.pricing_prompt)}, completion {_format_price(model.pricing_completion)}")
    keyboard = _models_page_keyboard(page=page, total_pages=total_pages, page_models=page_models, favorite_slugs=favorites)
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, "\n".join(lines), keyboard)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "fav_pick"), AdminFilter())
async def cb_fav_pick(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    try:
        page = int(callback_data.arg1)
        idx = int(callback_data.arg2)
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    models_data = data.get("models") or []
    absolute_idx = page * _PAGE_SIZE + idx
    if absolute_idx < 0 or absolute_idx >= len(models_data):
        await callback.answer("Модель не найдена", show_alert=True)
        return
    slug = models_data[absolute_idx].get("id") or ""
    if not slug:
        await callback.answer("Модель без id", show_alert=True)
        return
    store = get_settings_store()
    added, _ = await store.toggle_openrouter_favorite_model(
        slug, by_user_id=callback.from_user.id
    )
    await callback.answer("Добавлено в избранное" if added else "Убрано из избранного")
    await _render_models_page(callback, state, page=page)


__all__ = ["settings_router", "SettingsStates"]
