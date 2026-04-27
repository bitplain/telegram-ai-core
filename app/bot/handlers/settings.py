"""Admin /settings: inline-меню для управления OpenRouter ключом и model overrides.

Доступно только админам (``ADMIN_TELEGRAM_USER_IDS``), все ответы про секреты —
без раскрытия значения. Используется FSM (``MemoryStorage``) для:
- ввода нового API-ключа,
- хранения текущей страницы списка моделей и самого списка
  (чтобы не раздувать ``callback_data`` сверх 64-байтного лимита Telegram).

Валидация ключа: префикс ``sk-or-v1-`` + тестовый ``GET /api/v1/key`` с этим
ключом. При HTTP 200 — сохраняем; при ошибке — повторно prompt-им.
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
from app.config import get_settings
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


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------


class SettingsStates(StatesGroup):
    awaiting_api_key = State()
    awaiting_model_for_profile = State()


# ---------------------------------------------------------------------------
# Callback factory (короткий prefix — экономим callback_data до 64 байт)
# ---------------------------------------------------------------------------


class SettingsCB(CallbackData, prefix="s"):
    action: str
    arg1: str = ""
    arg2: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_key(value: str) -> str:
    """Маскирует API-ключ для безопасного отображения: ``sk-or-...XXXX``."""
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:7]}...{value[-4:]}"


def _format_price(price: float | None) -> str:
    if price is None:
        return "?"
    # OpenRouter отдаёт цену за токен; нагляднее — за 1M токенов.
    return f"${price * 1_000_000:.2f}/1M"


def _root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Установить OpenRouter API key",
                    callback_data=SettingsCB(action="apikey").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сменить модель",
                    callback_data=SettingsCB(action="profiles").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Обновить список моделей",
                    callback_data=SettingsCB(action="refresh").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сбросить настройки",
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


def _profiles_keyboard() -> InlineKeyboardMarkup:
    """Список ModelProfile-ов как inline-кнопки."""
    rows: list[list[InlineKeyboardButton]] = []
    for profile in get_model_registry().list_enabled():
        rows.append(
            [
                InlineKeyboardButton(
                    text=profile.display_name,
                    callback_data=SettingsCB(
                        action="profile", arg1=profile.id
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=SettingsCB(action="root").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _models_page_keyboard(
    *, page: int, total_pages: int, page_models: list[ModelInfo]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, model in enumerate(page_models):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{model.provider} / {model.name}"[:64],
                    # arg1 — page (как строка), arg2 — индекс в списке этой страницы
                    callback_data=SettingsCB(
                        action="pick", arg1=str(page), arg2=str(idx)
                    ).pack(),
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


# ---------------------------------------------------------------------------
# /settings command
# ---------------------------------------------------------------------------


@settings_router.message(Command("settings"), AdminFilter())
async def cmd_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    store = get_settings_store()
    api_key = await store.get_openrouter_api_key()
    has_db_key = await store.has_db_openrouter_api_key()
    overrides = await store.list_model_overrides()

    src = "БД" if has_db_key else ("ENV" if api_key else "не задан")
    masked = _mask_key(api_key or "")
    if api_key and src == "БД":
        key_line = f"Текущий ключ: <b>{src}</b> ({masked})"
    elif api_key:
        key_line = f"Текущий ключ: <b>{src}</b> ({masked})"
    else:
        key_line = "Текущий ключ: <b>не задан</b>"

    overrides_block = ""
    if overrides:
        lines = "\n".join(
            f"• <code>{model_id}</code> → <code>{name}</code>"
            for model_id, name in sorted(overrides.items())
        )
        overrides_block = f"\n\nАктивные model overrides:\n{lines}"

    text = (
        "<b>Admin · /settings</b>\n\n"
        f"{key_line}\n"
        f"Шифрование БД: <b>"
        f"{'включено' if store.encryption_enabled else 'выключено (plaintext)'}</b>"
        f"{overrides_block}"
    )
    await message.answer(text, reply_markup=_root_keyboard())


# ---------------------------------------------------------------------------
# Корневое меню
# ---------------------------------------------------------------------------


@settings_router.callback_query(
    SettingsCB.filter(F.action == "root"), AdminFilter()
)
async def cb_root(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "<b>Admin · /settings</b>\n\nВыберите действие.",
            reply_markup=_root_keyboard(),
        )
    await callback.answer()


@settings_router.callback_query(
    SettingsCB.filter(F.action == "noop"), AdminFilter()
)
async def cb_noop(callback: CallbackQuery, callback_data: SettingsCB) -> None:
    await callback.answer()


@settings_router.callback_query(
    SettingsCB.filter(F.action == "close"), AdminFilter()
)
async def cb_close(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text("Закрыто.")
        except Exception:  # noqa: BLE001
            log.debug("close: edit_text failed", exc_info=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# Установка API key (FSM awaiting_api_key)
# ---------------------------------------------------------------------------


@settings_router.callback_query(
    SettingsCB.filter(F.action == "apikey"), AdminFilter()
)
async def cb_apikey(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    await state.set_state(SettingsStates.awaiting_api_key)
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            log.debug("apikey: edit_reply_markup failed", exc_info=True)
        await callback.message.answer(
            "Отправь новый OpenRouter API key одним сообщением "
            f"(префикс <code>{_API_KEY_PREFIX}</code>).\n"
            "Ключ будет проверен через <code>GET /api/v1/key</code> и сохранён."
        )
    await callback.answer()


@settings_router.message(SettingsStates.awaiting_api_key, AdminFilter())
async def on_api_key_message(message: Message, state: FSMContext) -> None:
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

    # Удалим сообщение пользователя, чтобы ключ не светился в чате.
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        log.debug("Could not delete user message with API key", exc_info=True)

    ok, detail = await _validate_openrouter_key(raw)
    if not ok:
        await message.answer(
            f"Ключ не прошёл валидацию: {detail}\nПопробуй ещё раз или /cancel."
        )
        return

    if message.from_user is None:
        await state.clear()
        return
    store = get_settings_store()
    await store.set_openrouter_api_key(raw, by_user_id=message.from_user.id)
    await state.clear()

    enc = "включено" if store.encryption_enabled else "выключено (plaintext)"
    await message.answer(
        f"Ключ обновлён. Шифрование: <b>{enc}</b>.\n{detail}",
        reply_markup=_root_keyboard(),
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
    """``GET /api/v1/key`` с переданным Bearer. True если 2xx."""
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
        except Exception:  # noqa: BLE001
            log.debug("Failed to parse /key response", exc_info=True)
        return True, "ключ валиден"
    if response.status_code in (401, 403):
        return False, "Telegram отверг ключ (401/403)"
    return False, f"HTTP {response.status_code}"


# ---------------------------------------------------------------------------
# Сброс
# ---------------------------------------------------------------------------


@settings_router.callback_query(
    SettingsCB.filter(F.action == "reset"), AdminFilter()
)
async def cb_reset(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    await state.clear()
    store = get_settings_store()
    await store.reset_all_overrides()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                "Все model overrides удалены. API-ключ остался без изменений.",
                reply_markup=_root_keyboard(),
            )
        except Exception:  # noqa: BLE001
            log.debug("reset: edit_text failed", exc_info=True)
    await callback.answer("Готово")


# ---------------------------------------------------------------------------
# Refresh — принудительно перетянуть список моделей
# ---------------------------------------------------------------------------


@settings_router.callback_query(
    SettingsCB.filter(F.action == "refresh"), AdminFilter()
)
async def cb_refresh(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    await state.clear()
    models = await get_openrouter_models_client().fetch(force=True)
    text = f"Список моделей обновлён. Доступно: <b>{len(models)}</b>."
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text, reply_markup=_root_keyboard()
            )
        except Exception:  # noqa: BLE001
            await callback.message.answer(text, reply_markup=_root_keyboard())
    await callback.answer("Готово")


# ---------------------------------------------------------------------------
# Profiles → выбор ModelProfile
# ---------------------------------------------------------------------------


@settings_router.callback_query(
    SettingsCB.filter(F.action == "profiles"), AdminFilter()
)
async def cb_profiles(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                "Выберите профиль модели для переопределения:",
                reply_markup=_profiles_keyboard(),
            )
        except Exception:  # noqa: BLE001
            await callback.message.answer(
                "Выберите профиль модели для переопределения:",
                reply_markup=_profiles_keyboard(),
            )
    await callback.answer()


@settings_router.callback_query(
    SettingsCB.filter(F.action == "profile"), AdminFilter()
)
async def cb_profile(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    profile_id = callback_data.arg1
    profile = get_model_registry().get_or_none(profile_id)
    if profile is None:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    models = await get_openrouter_models_client().fetch(force=False)
    if not models:
        await callback.answer(
            "Список моделей пуст. Сначала «Обновить список моделей».",
            show_alert=True,
        )
        return

    await state.set_state(SettingsStates.awaiting_model_for_profile)
    # Сохраняем full list + profile_id в FSM, чтобы callback_data оставался
    # коротким (только индекс модели на странице).
    await state.update_data(
        profile_id=profile_id,
        # ModelInfo dataclass — сериализуем в dict-ы для хранения в FSM.
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


@settings_router.callback_query(
    SettingsCB.filter(F.action == "page"), AdminFilter()
)
async def cb_page(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    try:
        page = int(callback_data.arg1)
    except ValueError:
        await callback.answer()
        return
    await _render_models_page(callback, state, page=page)


async def _render_models_page(
    callback: CallbackQuery, state: FSMContext, *, page: int
) -> None:
    data = await state.get_data()
    models_data = data.get("models") or []
    profile_id = data.get("profile_id") or ""
    if not models_data or not profile_id:
        await callback.answer(
            "Сессия истекла, открой /settings заново.", show_alert=True
        )
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

    keyboard = _models_page_keyboard(
        page=page, total_pages=total_pages, page_models=page_models
    )
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                "\n".join(lines), reply_markup=keyboard
            )
        except Exception:  # noqa: BLE001
            await callback.message.answer(
                "\n".join(lines), reply_markup=keyboard
            )
    await callback.answer()


@settings_router.callback_query(
    SettingsCB.filter(F.action == "pick"), AdminFilter()
)
async def cb_pick(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
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
        await callback.answer(
            "Сессия истекла, открой /settings заново.", show_alert=True
        )
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
    text = (
        f"Профиль <b>{title}</b> теперь использует модель "
        f"<code>{chosen_id}</code>."
    )
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=_root_keyboard())
        except Exception:  # noqa: BLE001
            await callback.message.answer(text, reply_markup=_root_keyboard())
    await callback.answer("Сохранено")


__all__ = ["settings_router", "SettingsStates"]
