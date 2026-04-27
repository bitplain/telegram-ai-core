"""Admin /settings: API settings and per-user agent settings."""

from __future__ import annotations

import logging

import httpx
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
_API_KEY_PREFIX = "sk-or-v1-"
_VALIDATE_URL = "https://openrouter.ai/api/v1/key"
_PROMPT_PREVIEW_CHARS = 500


class SettingsStates(StatesGroup):
    awaiting_openrouter_api_key = State()
    awaiting_yandex_api_key = State()
    awaiting_agent_prompt = State()
    awaiting_model_for_profile = State()


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
        "<code>ADMIN_TELEGRAM_USER_IDS</code>."
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


def _openrouter_keyboard(*, has_key: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="+ API", callback_data=SettingsCB(action="openrouter_add_api").pack())]
    ]
    if has_key:
        rows.append([InlineKeyboardButton(text="Выбрать модель", callback_data=SettingsCB(action="profiles").pack())])
        rows.append([InlineKeyboardButton(text="Обновить список моделей", callback_data=SettingsCB(action="refresh").pack())])
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


def _agent_models_keyboard(agent_id: str, service: UserAgentSettingsService | None = None) -> InlineKeyboardMarkup:
    service = service or UserAgentSettingsService()
    rows = [
        [
            InlineKeyboardButton(
                text=model.id,
                callback_data=SettingsCB(action="agent_set_model", arg1=agent_id, arg2=model.id).pack(),
            )
        ]
        for model in service.list_enabled_models()
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="agent", arg1=agent_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _profiles_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for profile in get_model_registry().list_enabled():
        rows.append([InlineKeyboardButton(text=profile.display_name, callback_data=SettingsCB(action="profile", arg1=profile.id).pack())])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="provider", arg1="openrouter").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _models_page_keyboard(*, page: int, total_pages: int, page_models: list[ModelInfo]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, model in enumerate(page_models):
        rows.append([InlineKeyboardButton(text=f"{model.provider} / {model.name}"[:64], callback_data=SettingsCB(action="pick", arg1=str(page), arg2=str(idx)).pack())])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="‹", callback_data=SettingsCB(action="page", arg1=str(page - 1)).pack()))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data=SettingsCB(action="noop").pack()))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="›", callback_data=SettingsCB(action="page", arg1=str(page + 1)).pack()))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SettingsCB(action="profiles").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _settings_status_text() -> str:
    store = get_settings_store()
    openrouter_api_key = await store.get_openrouter_api_key()
    has_db_openrouter_key = await store.has_db_openrouter_api_key()
    yandex_api_key = await store.get_yandex_api_key()
    has_db_yandex_key = await store.has_db_yandex_api_key()

    openrouter_src = "БД" if has_db_openrouter_key else ("ENV" if openrouter_api_key else "не задан")
    yandex_src = "БД" if has_db_yandex_key else "не задан"
    openrouter_line = f"OpenRouter: <b>{openrouter_src}</b>" + (f" ({_mask_key(openrouter_api_key or '')})" if openrouter_api_key else "")
    yandex_line = f"Yandex: <b>{yandex_src}</b>" + (f" ({_mask_key(yandex_api_key or '')})" if yandex_api_key else "")
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
    store = get_settings_store()
    api_key = await store.get_openrouter_api_key()
    has_key = bool(api_key)
    source = "БД" if await store.has_db_openrouter_api_key() else ("ENV" if api_key else "не задан")
    body = ["<b>OpenRouter</b>"]
    body.append(f"Ключ: <b>{source}</b> ({_mask_key(api_key or '')})" if has_key else "Ключ: <b>не задан</b>")
    body.append("Добавьте ключ через + API. После успешной проверки откроется выбор моделей.")
    await _edit_or_answer(message, "\n\n".join(body), _openrouter_keyboard(has_key=has_key))


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
        f"Модель: <code>{settings.effective_model.id}</code> ({model_source})\n"
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
    if isinstance(callback.message, Message):
        await _edit_or_answer(
            callback.message,
            f"<b>Выберите модель для агента {settings.agent.name}</b>:",
            _agent_models_keyboard(settings.agent.id, service),
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
        await callback.message.answer(f"Модель для агента <b>{settings.agent.name}</b> сохранена: <code>{settings.effective_model.id}</code>")
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


@settings_router.callback_query(SettingsCB.filter(F.action == "openrouter_add_api"), AdminFilter())
async def cb_openrouter_add_api(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.set_state(SettingsStates.awaiting_openrouter_api_key)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отправьте OpenRouter API key одним сообщением "
            f"(префикс <code>{_API_KEY_PREFIX}</code>).\n"
            "Ключ будет проверен через <code>GET /api/v1/key</code>."
        )
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


@settings_router.message(SettingsStates.awaiting_openrouter_api_key, AdminFilter())
async def on_openrouter_api_key_message(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение. Отправьте ключ ещё раз или /cancel.")
        return
    if not raw.startswith(_API_KEY_PREFIX):
        await message.answer(f"Ожидается ключ с префиксом <code>{_API_KEY_PREFIX}</code>. Попробуйте ещё раз или /cancel.")
        return
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        log.debug("Could not delete user message with OpenRouter API key", exc_info=True)
    ok, detail = await _validate_openrouter_key(raw)
    if not ok:
        await message.answer(f"Ключ не прошёл валидацию: {detail}\nПопробуйте ещё раз или /cancel.")
        return
    if message.from_user is None:
        await state.clear()
        return
    store = get_settings_store()
    await store.set_openrouter_api_key(raw, by_user_id=message.from_user.id)
    await state.clear()
    enc = "включено" if store.encryption_enabled else "выключено (plaintext)"
    await message.answer(f"OpenRouter ключ обновлён. Шифрование: <b>{enc}</b>.\n{detail}", reply_markup=_openrouter_keyboard(has_key=True))


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


async def _validate_openrouter_key(api_key: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(_VALIDATE_URL, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        return False, f"сетевая ошибка ({exc.__class__.__name__})"
    if 200 <= response.status_code < 300:
        try:
            data = response.json()
            payload = data.get("data") or {}
            limit = payload.get("limit")
            usage = payload.get("usage")
            if limit is not None and usage is not None:
                return True, f"квота {usage} / {limit}"
        except Exception:  # noqa: BLE001
            log.debug("Failed to parse /key response", exc_info=True)
        return True, "ключ валиден"
    if response.status_code in (401, 403):
        return False, "OpenRouter отверг ключ (401/403)"
    return False, f"HTTP {response.status_code}"


@settings_router.callback_query(SettingsCB.filter(F.action == "reset"), AdminFilter())
async def cb_reset(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    store = get_settings_store()
    await store.reset_all_overrides()
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, "Все model overrides удалены. API-ключи остались без изменений.", _api_keyboard())
    await callback.answer("Готово")


@settings_router.callback_query(SettingsCB.filter(F.action == "refresh"), AdminFilter())
async def cb_refresh(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    models = await get_openrouter_models_client().fetch(force=True)
    text = f"Список моделей обновлён. Доступно: <b>{len(models)}</b>."
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, text, _openrouter_keyboard(has_key=True))
    await callback.answer("Готово")


@settings_router.callback_query(SettingsCB.filter(F.action == "profiles"), AdminFilter())
async def cb_profiles(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, "Выберите профиль модели для переопределения:", _profiles_keyboard())
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "profile"), AdminFilter())
async def cb_profile(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    profile_id = callback_data.arg1
    profile = get_model_registry().get_or_none(profile_id)
    if profile is None:
        await callback.answer("Профиль не найден", show_alert=True)
        return
    models = await get_openrouter_models_client().fetch(force=False)
    if not models:
        await callback.answer("Список моделей пуст. Сначала «Обновить список моделей».", show_alert=True)
        return
    await state.set_state(SettingsStates.awaiting_model_for_profile)
    await state.update_data(
        profile_id=profile_id,
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
        ],
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
    profile_id = data.get("profile_id") or ""
    if not models_data or not profile_id:
        await callback.answer("Сессия истекла, откройте /settings заново.", show_alert=True)
        return
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
    profile = get_model_registry().get_or_none(profile_id)
    title = profile.display_name if profile else profile_id
    lines = [f"<b>Модели для профиля</b>: {title}", ""]
    for idx, model in enumerate(page_models):
        lines.append(f"{idx + 1}. <code>{model.id}</code> — prompt {_format_price(model.pricing_prompt)}, completion {_format_price(model.pricing_completion)}")
    keyboard = _models_page_keyboard(page=page, total_pages=total_pages, page_models=page_models)
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, "\n".join(lines), keyboard)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "pick"), AdminFilter())
async def cb_pick(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    try:
        page = int(callback_data.arg1)
        idx = int(callback_data.arg2)
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    models_data = data.get("models") or []
    profile_id = data.get("profile_id") or ""
    if not models_data or not profile_id:
        await callback.answer("Сессия истекла, откройте /settings заново.", show_alert=True)
        return
    absolute_idx = page * _PAGE_SIZE + idx
    if absolute_idx < 0 or absolute_idx >= len(models_data):
        await callback.answer("Модель не найдена", show_alert=True)
        return
    chosen_id = models_data[absolute_idx].get("id") or ""
    if not chosen_id:
        await callback.answer("Модель без id", show_alert=True)
        return
    store = get_settings_store()
    await store.set_model_override(profile_id, chosen_id, by_user_id=callback.from_user.id)
    await state.clear()
    profile = get_model_registry().get_or_none(profile_id)
    title = profile.display_name if profile else profile_id
    text = f"Профиль <b>{title}</b> теперь использует модель <code>{chosen_id}</code>."
    if isinstance(callback.message, Message):
        await _edit_or_answer(callback.message, text, _openrouter_keyboard(has_key=True))
    await callback.answer("Сохранено")


__all__ = ["settings_router", "SettingsStates"]
