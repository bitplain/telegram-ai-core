"""Список моделей OpenRouter c Redis-кешем для admin /settings.

Эндпоинт ``GET https://openrouter.ai/api/v1/models`` публичный и не требует
авторизации. Сортировка результата:
1. «Топ-провайдеры» (openai, anthropic, google, meta-llama, mistralai) — выше.
2. Внутри каждого провайдера — по цене (prompt + completion), от дешёвых к дорогим.
3. Модели без цены идут в конец своей группы.

Кеш: ``openrouter:models:v1`` в Redis на 12 часов; ``force=True`` сбрасывает.
Если Redis недоступен — каждый вызов ходит в API напрямую (graceful).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

import httpx

from app.config import get_settings
from app.redis.client import get_redis

log = logging.getLogger(__name__)


REDIS_CACHE_KEY = "openrouter:models:v1"
CACHE_TTL_SECONDS = 12 * 3600
_API_URL = "https://openrouter.ai/api/v1/models"
_TOP_PROVIDERS_ORDER = (
    "openai",
    "anthropic",
    "google",
    "meta-llama",
    "mistralai",
)


@dataclass(slots=True, frozen=True)
class ModelInfo:
    """Минимальный набор полей модели OpenRouter, нужный для UI выбора."""

    id: str  # OpenRouter slug, например "openai/gpt-4.1-mini"
    name: str  # человекочитаемое имя
    provider: str  # "openai" / "anthropic" / ...
    context_length: int | None
    pricing_prompt: float | None  # USD за 1 токен (как у OpenRouter)
    pricing_completion: float | None


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_model(item: dict) -> ModelInfo | None:
    model_id = str(item.get("id") or "").strip()
    if not model_id:
        return None
    name = str(item.get("name") or model_id)
    provider = model_id.split("/", 1)[0] if "/" in model_id else "unknown"
    pricing = item.get("pricing") or {}
    return ModelInfo(
        id=model_id,
        name=name,
        provider=provider,
        context_length=_safe_int(item.get("context_length")),
        pricing_prompt=_safe_float(pricing.get("prompt")),
        pricing_completion=_safe_float(pricing.get("completion")),
    )


def _sort_key(model: ModelInfo) -> tuple[int, float, str]:
    try:
        provider_rank = _TOP_PROVIDERS_ORDER.index(model.provider)
    except ValueError:
        provider_rank = len(_TOP_PROVIDERS_ORDER)

    # Сумма цен — простой и стабильный прокси «дешевизны».
    prices = [
        p for p in (model.pricing_prompt, model.pricing_completion) if p is not None
    ]
    price = sum(prices) if prices else float("inf")
    return provider_rank, price, model.name.lower()


class OpenRouterModelsClient:
    """Async-клиент к ``GET /api/v1/models`` c Redis-кешем."""

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(30.0)

    async def fetch(self, *, force: bool = False) -> list[ModelInfo]:
        if not force:
            cached = await self._cache_get()
            if cached is not None:
                return cached

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    _API_URL,
                    headers={
                        "HTTP-Referer": get_settings().OPENROUTER_SITE_URL,
                        "X-Title": get_settings().OPENROUTER_APP_NAME,
                    },
                )
        except httpx.HTTPError as exc:
            log.warning(
                "Failed to fetch OpenRouter models: %s", exc.__class__.__name__
            )
            cached = await self._cache_get()
            return cached or []

        if response.status_code >= 400:
            log.warning(
                "OpenRouter /models returned HTTP %s; falling back to cache",
                response.status_code,
            )
            cached = await self._cache_get()
            return cached or []

        try:
            payload = response.json()
        except json.JSONDecodeError:
            log.warning("OpenRouter /models returned non-JSON body")
            return []

        items = payload.get("data") or []
        models: list[ModelInfo] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            parsed = _parse_model(raw)
            if parsed is not None:
                models.append(parsed)

        models.sort(key=_sort_key)
        await self._cache_set(models)
        return models

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _cache_get() -> list[ModelInfo] | None:
        client = get_redis()
        if client is None:
            return None
        try:
            raw = await client.get(REDIS_CACHE_KEY)
        except Exception:  # noqa: BLE001
            log.debug("Redis GET failed for models cache", exc_info=True)
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return None
        out: list[ModelInfo] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                out.append(ModelInfo(**item))
            except TypeError:
                continue
        return out or None

    @staticmethod
    async def _cache_set(models: list[ModelInfo]) -> None:
        client = get_redis()
        if client is None:
            return
        try:
            payload = json.dumps([asdict(m) for m in models], ensure_ascii=False)
            await client.set(REDIS_CACHE_KEY, payload, ex=CACHE_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            log.debug("Redis SET failed for models cache", exc_info=True)


_singleton: OpenRouterModelsClient | None = None


def get_openrouter_models_client() -> OpenRouterModelsClient:
    global _singleton
    if _singleton is None:
        _singleton = OpenRouterModelsClient()
    return _singleton


__all__ = [
    "ModelInfo",
    "OpenRouterModelsClient",
    "get_openrouter_models_client",
    "REDIS_CACHE_KEY",
    "CACHE_TTL_SECONDS",
]
