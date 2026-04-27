"""Admin /settings: inline-меню для управления API-провайдерами и model overrides.

Доступно только админам (``ADMIN_TELEGRAM_USER_IDS``), все ответы про секреты —
без раскрытия значения. Используется FSM (``MemoryStorage``) для:
- ввода OpenRouter API-ключа,
- ввода Yandex API-ключа (заглушка),
- хранения текущей страницы списка моделей и самого списка
  (чтобы не раздувать ``callback_data`` сверх 64-байтного лимита Telegram).

OpenRouter-валидация: префикс ``sk-or-v1-`` + тестовый ``GET /api/v1/key``.
"""

from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.filters.admin import AdminFilter
from app.core.settings_store import get_settings_store
from app.llm.openrouter_models import (
    ModelInfo,
    get_openrouter_models_client,
)
from app.models.registry import get_model_registry

log = logging.getLogger(__name__)

settings_router = Router(name="settings")

_PAGE_SIZE = 8
_API_KEY_PREFIX = "sk-or-v1-"
_VALIDATE_URL = "https://openrouter.ai/api/v1/key"


def _looks_like_settings_command(text: str | None) -> bool:
    if not text:
        return False
    cmd = text.strip().split(maxsplit=1)[0].lower()
    if not cmd.startswith("/settings"):
        return False
    return cmd == "/settings" or cmd.startswith("/settings@")


class SettingsStates(StatesGroup):
    awaiting_openrouter_api_key = State()
    awaiting_yandex_api_key = State()
    awaiting_model_for_profile = State()


class SettingsCB(CallbackData, prefix="s"):
    action: str
    arg1: str = ""
    arg2: str = ""


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


def _root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить API",
                    callback_data=SettingsCB(action="providers").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сбросить настройки моделей",
                    callback_data=SettingsCB(action="reset").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Закрыть",
                    callback_data=SettingsCB(action="close").pack(),
                )
            ],
        ]
    )


def _providers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="OpenRouter",
                    callback_data=SettingsCB(action="provider", arg1="openrouter").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Яндекс",
                    callback_data=SettingsCB(action="provider", arg1="yandex").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=SettingsCB(action="root").pack(),
                )
            ],
        ]
    )


def _openrouter_keyboard(*, has_key: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="+ API",
                callback_data=SettingsCB(action="openrouter_add_api").pack(),
            )
        ]
    ]
    if has_key:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Выбрать модель",
                    callback_data=SettingsCB(action="profiles").pack(),
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Обновить список моделей",
                    callback_data=SettingsCB(action="refresh").pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=SettingsCB(action="providers").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _yandex_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="+ API",
                    callback_data=SettingsCB(action="yandex_add_api").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=SettingsCB(action="providers").pack(),
                )
            ],
        ]
    )


def _profiles_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for profile in get_model_registry().list_enabled():
        rows.append(
            [
                InlineKeyboardButton(
                    text=profile.display_name,
                    callback_data=SettingsCB(action="profile", arg1=profile.id).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=SettingsCB(action="provider", arg1="openrouter").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _models_page_keyboard(*, page: int, total_pages: int, page_models: list[ModelInfo]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, model in enumerate(page_models):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{model.provider} / {model.name}"[:64],
                    callback_data=SettingsCB(action="pick", arg1=str(page), arg2=str(idx)).pack(),
                )
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="‹",
                callback_data=SettingsCB(action="page", arg1=str(page - 1)).pack(),
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data=SettingsCB(action="noop").pack(),
        )
    )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="›",
                callback_data=SettingsCB(action="page", arg1=str(page + 1)).pack(),
            )
        )
    if nav:
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=SettingsCB(action="profiles").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_root_message(message: Message) -> None:
    store = get_settings_store()
    openrouter_api_key = await store.get_openrouter_api_key()
    has_db_openrouter_key = await store.has_db_openrouter_api_key()
    yandex_api_key = await store.get_yandex_api_key()
    has_db_yandex_key = await store.has_db_yandex_api_key()

    openrouter_src = "БД" if has_db_openrouter_key else ("ENV" if openrouter_api_key else "не задан")
    yandex_src = "БД" if has_db_yandex_key else "не задан"

    openrouter_line = (
        f"OpenRouter: <b>{openrouter_src}</b>"
        + (f" ({_mask_key(openrouter_api_key or '')})" if openrouter_api_key else "")
    )
    yandex_line = (
        f"Yandex: <b>{yandex_src}</b>"
        + (f" ({_mask_key(yandex_api_key or '')})" if yandex_api_key else "")
    )

    text = (
        "<b>Admin · /settings</b>\n\n"
        f"{openrouter_line}\n"
        f"{yandex_line}\n"
        f"Шифрование БД: <b>{'включено' if store.encryption_enabled else 'выключено (plaintext)'}</b>"
    )
    await message.answer(text, reply_markup=_root_keyboard())


async def _render_provider_menu(message: Message) -> None:
    await message.edit_text("Выберите провайдера API:", reply_markup=_providers_keyboard())


async def _render_openrouter_menu(message: Message) -> None:
    store = get_settings_store()
    api_key = await store.get_openrouter_api_key()
    has_key = bool(api_key)
    source = "БД" if await store.has_db_openrouter_api_key() else ("ENV" if api_key else "не задан")
    body = ["<b>OpenRouter</b>"]
    if has_key:
        body.append(f"Ключ: <b>{source}</b> ({_mask_key(api_key or '')})")
    else:
        body.append("Ключ: <b>не задан</b>")
    body.append("Добавьте ключ через + API. После успешной проверки откроется выбор моделей.")
    await message.edit_text("\n\n".join(body), reply_markup=_openrouter_keyboard(has_key=has_key))


async def _render_yandex_menu(message: Message) -> None:
    store = get_settings_store()
    api_key = await store.get_yandex_api_key()
    source = "БД" if await store.has_db_yandex_api_key() else "не задан"
    body = ["<b>Яндекс (заглушка)</b>"]
    if api_key:
        body.append(f"Ключ: <b>{source}</b> ({_mask_key(api_key)})")
    else:
        body.append("Ключ: <b>не задан</b>")
    body.append("Провайдер пока не подключен к runtime. + API сохраняет ключ в настройки.")
    await message.edit_text("\n\n".join(body), reply_markup=_yandex_keyboard())


@settings_router.message(Command("settings"), AdminFilter())
async def cmd_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _render_root_message(message)


@settings_router.message(F.text.func(_looks_like_settings_command), AdminFilter())
async def cmd_settings_text_button(message: Message, state: FSMContext) -> None:
    """Fallback для кнопок меню, которые присылают /settings обычным текстом."""
    await state.clear()
    await _render_root_message(message)


@settings_router.callback_query(SettingsCB.filter(F.action == "root"), AdminFilter())
async def cb_root(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("<b>Admin · /settings</b>\n\nВыберите действие.", reply_markup=_root_keyboard())
        except Exception:
            await _render_root_message(callback.message)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "providers"), AdminFilter())
async def cb_providers(callback: CallbackQuery, callback_data: SettingsCB) -> None:
    if isinstance(callback.message, Message):
        try:
            await _render_provider_menu(callback.message)
        except Exception:
            await callback.message.answer("Выберите провайдера API:", reply_markup=_providers_keyboard())
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "provider"), AdminFilter())
async def cb_provider(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    try:
        if callback_data.arg1 == "openrouter":
            await _render_openrouter_menu(callback.message)
        elif callback_data.arg1 == "yandex":
            await _render_yandex_menu(callback.message)
        else:
            await _render_provider_menu(callback.message)
    except Exception:
        log.debug("provider menu render failed", exc_info=True)
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
        except Exception:
            log.debug("close: edit_text failed", exc_info=True)
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "openrouter_add_api"), AdminFilter())
async def cb_openrouter_add_api(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.set_state(SettingsStates.awaiting_openrouter_api_key)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отправь OpenRouter API key одним сообщением "
            f"(префикс <code>{_API_KEY_PREFIX}</code>).\n"
            "Ключ будет проверен через <code>GET /api/v1/key</code>."
        )
    await callback.answer()


@settings_router.callback_query(SettingsCB.filter(F.action == "yandex_add_api"), AdminFilter())
async def cb_yandex_add_api(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.set_state(SettingsStates.awaiting_yandex_api_key)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Отправь Yandex API key одним сообщением.\n"
            "Это заглушка: ключ сохранится, но пока не используется в runtime."
        )
    await callback.answer()


@settings_router.message(SettingsStates.awaiting_openrouter_api_key, AdminFilter())
async def on_openrouter_api_key_message(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение. Отправь ключ ещё раз или /cancel.")
        return
    if not raw.startswith(_API_KEY_PREFIX):
        await message.answer(
            f"Ожидается ключ с префиксом <code>{_API_KEY_PREFIX}</code>. "
            "Попробуй ещё раз или /cancel."
        )
        return

    try:
        await message.delete()
    except Exception:
        log.debug("Could not delete user message with OpenRouter API key", exc_info=True)

    ok, detail = await _validate_openrouter_key(raw)
    if not ok:
        await message.answer(f"Ключ не прошёл валидацию: {detail}\nПопробуй ещё раз или /cancel.")
        return

    if message.from_user is None:
        await state.clear()
        return

    store = get_settings_store()
    await store.set_openrouter_api_key(raw, by_user_id=message.from_user.id)
    await state.clear()

    enc = "включено" if store.encryption_enabled else "выключено (plaintext)"
    await message.answer(
        f"OpenRouter ключ обновлён. Шифрование: <b>{enc}</b>.\n{detail}",
        reply_markup=_openrouter_keyboard(has_key=True),
    )


@settings_router.message(SettingsStates.awaiting_yandex_api_key, AdminFilter())
async def on_yandex_api_key_message(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Пустое сообщение. Отправь ключ ещё раз или /cancel.")
        return

    try:
        await message.delete()
    except Exception:
        log.debug("Could not delete user message with Yandex API key", exc_info=True)

    if message.from_user is None:
        await state.clear()
        return

    store = get_settings_store()
    await store.set_yandex_api_key(raw, by_user_id=message.from_user.id)
    await state.clear()

    await message.answer(
        "Yandex API key сохранён как заглушка. Интеграция провайдера пока не подключена.",
        reply_markup=_yandex_keyboard(),
    )


@settings_router.message(Command("cancel"), AdminFilter())
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Отменять нечего.")
        return
    await state.clear()
    await message.answer("Отменено.", reply_markup=_root_keyboard())


async def _validate_openrouter_key(api_key: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(
                _VALIDATE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
            )
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
        except Exception:
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
        try:
            await callback.message.edit_text(
                "Все model overrides удалены. API-ключи остались без изменений.",
                reply_markup=_root_keyboard(),
            )
        except Exception:
            log.debug("reset: edit_text failed", exc_info=True)
    await callback.answer("Готово")


@settings_router.callback_query(SettingsCB.filter(F.action == "refresh"), AdminFilter())
async def cb_refresh(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    await state.clear()
    models = await get_openrouter_models_client().fetch(force=True)
    text = f"Список моделей обновлён. Доступно: <b>{len(models)}</b>."
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=_openrouter_keyboard(has_key=True))
        except Exception:
            await callback.message.answer(text, reply_markup=_openrouter_keyboard(has_key=True))
    await callback.answer("Готово")


@settings_router.callback_query(SettingsCB.filter(F.action == "profiles"), AdminFilter())
async def cb_profiles(callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext) -> None:
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                "Выберите профиль модели для переопределения:",
                reply_markup=_profiles_keyboard(),
            )
        except Exception:
            await callback.message.answer(
                "Выберите профиль модели для переопределения:",
                reply_markup=_profiles_keyboard(),
            )
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
        await callback.answer("Сессия истекла, открой /settings заново.", show_alert=True)
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
        lines.append(
            f"{idx + 1}. <code>{model.id}</code> — "
            f"prompt {_format_price(model.pricing_prompt)}, "
            f"completion {_format_price(model.pricing_completion)}"
        )

    keyboard = _models_page_keyboard(page=page, total_pages=total_pages, page_models=page_models)
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("\n".join(lines), reply_markup=keyboard)
        except Exception:
            await callback.message.answer("\n".join(lines), reply_markup=keyboard)
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
        await callback.answer("Сессия истекла, открой /settings заново.", show_alert=True)
        return

    absolute_idx = page * _PAGE_SIZE + idx
    if absolute_idx < 0 or absolute_idx >= len(models_data):
        await callback.answer("Модель не найдена", show_alert=True)
        return

    chosen = models_data[absolute_idx]
    chosen_id = chosen.get("id") or ""
    if not chosen_id:
        await callback.answer("Модель без id", show_alert=True)
        return

    user_id = callback.from_user.id if callback.from_user else 0
    store = get_settings_store()
    await store.set_model_override(profile_id, chosen_id, by_user_id=user_id)
    await state.clear()

    profile = get_model_registry().get_or_none(profile_id)
    title = profile.display_name if profile else profile_id
    text = f"Профиль <b>{title}</b> теперь использует модель <code>{chosen_id}</code>."
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=_openrouter_keyboard(has_key=True))
        except Exception:
            await callback.message.answer(text, reply_markup=_openrouter_keyboard(has_key=True))
    await callback.answer("Сохранено")


__all__ = ["settings_router", "SettingsStates"]
