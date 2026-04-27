"""OpenRouter клиент: streaming и non-streaming.

Используем httpx.AsyncClient + ручной разбор SSE.
Никогда не логируем API-ключ и тело Authorization.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.llm.schemas import ChatMessage, StreamUsage

log = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    """Любая ошибка обращения к OpenRouter, безопасная для проброса наружу."""


class OpenRouterAuthError(OpenRouterError):
    """API-ключ не задан или некорректен."""


@dataclass(slots=True)
class StreamingChunk:
    """Один кусочек стрима от LLM."""

    content_delta: str
    finish_reason: str | None = None


@dataclass(slots=True)
class CompletionResult:
    """Результат не-стримингового запроса."""

    content: str
    usage: StreamUsage | None = None


class OpenRouterClient:
    """Тонкий async-клиент над OpenRouter Chat Completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        site_url: str | None = None,
        app_name: str | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.OPENROUTER_API_KEY
        self._base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")
        self._timeout = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        self._site_url = site_url or settings.OPENROUTER_SITE_URL
        self._app_name = app_name or settings.OPENROUTER_APP_NAME
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """True, если ключ задан в ENV. Не учитывает БД-override."""
        return bool(self._api_key)

    async def is_configured_async(self) -> bool:
        """True, если ключ есть либо в ENV, либо в БД (через settings_store)."""
        if self._api_key:
            return True
        # Локальный импорт, чтобы избежать циклической зависимости.
        from app.core.settings_store import get_settings_store

        store = get_settings_store()
        return bool(await store.get_openrouter_api_key())

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    def _build_headers(self, api_key: str) -> dict[str, str]:
        if not api_key:
            raise OpenRouterAuthError("OPENROUTER_API_KEY is not set")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._site_url,
            "X-Title": self._app_name,
        }

    @staticmethod
    def _serialize_messages(messages: Iterable[ChatMessage | dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                out.append({"role": m.role, "content": m.content})
            else:
                out.append({"role": str(m["role"]), "content": str(m["content"])})
        return out

    async def stream_chat_completion(
        self,
        *,
        model: str,
        messages: Iterable[ChatMessage | dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
        api_key_override: str | None = None,
    ) -> AsyncIterator[StreamingChunk]:
        """Стриминговый chat/completions с парсингом SSE.

        Yield-ит StreamingChunk с дельтой контента. Аккуратно закрывает stream.
        При сетевых ошибках бросает OpenRouterError с человекочитаемым описанием.

        ``api_key_override`` позволяет orchestrator-у подсунуть ключ из БД
        (см. ``app.core.settings_store``) без перестройки клиента.
        """
        client = self._ensure_client()
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._serialize_messages(messages),
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        api_key = api_key_override or self._api_key
        try:
            async with client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                headers=self._build_headers(api_key),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    text = body.decode("utf-8", errors="replace")[:500]
                    log.error(
                        "OpenRouter HTTP %s on streaming completion",
                        response.status_code,
                        extra={"status_code": response.status_code},
                    )
                    raise OpenRouterError(
                        f"OpenRouter returned HTTP {response.status_code}: {text}"
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        log.warning("Failed to decode SSE chunk; skipping")
                        continue

                    chunk = self._chunk_from_event(event)
                    if chunk is None:
                        continue
                    yield chunk
                    if chunk.finish_reason is not None:
                        break
        except OpenRouterError:
            raise
        except httpx.HTTPError as exc:
            log.exception("OpenRouter network error")
            raise OpenRouterError(
                f"Сетевая ошибка при обращении к OpenRouter: {exc.__class__.__name__}"
            ) from exc

    @staticmethod
    def _chunk_from_event(event: dict[str, Any]) -> StreamingChunk | None:
        choices = event.get("choices") or []
        if not choices:
            return None
        first = choices[0]
        delta = first.get("delta") or {}
        content = delta.get("content") or ""
        finish = first.get("finish_reason")
        if not content and finish is None:
            # OpenRouter иногда шлёт служебные пустые куски — пропускаем.
            return None
        return StreamingChunk(content_delta=content or "", finish_reason=finish)

    async def chat_completion(
        self,
        *,
        model: str,
        messages: Iterable[ChatMessage | dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
        api_key_override: str | None = None,
    ) -> CompletionResult:
        """Не-стриминговый chat/completions для моделей без supports_streaming."""
        client = self._ensure_client()
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._serialize_messages(messages),
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra:
            payload.update(extra)

        api_key = api_key_override or self._api_key
        try:
            response = await client.post(
                "/chat/completions",
                json=payload,
                headers=self._build_headers(api_key),
            )
        except httpx.HTTPError as exc:
            log.exception("OpenRouter network error")
            raise OpenRouterError(
                f"Сетевая ошибка при обращении к OpenRouter: {exc.__class__.__name__}"
            ) from exc

        if response.status_code >= 400:
            text = response.text[:500]
            log.error(
                "OpenRouter HTTP %s on non-streaming completion",
                response.status_code,
                extra={"status_code": response.status_code},
            )
            raise OpenRouterError(
                f"OpenRouter returned HTTP {response.status_code}: {text}"
            )

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterError("OpenRouter returned response without choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""

        usage_data = data.get("usage") or {}
        usage = StreamUsage(
            prompt_tokens=usage_data.get("prompt_tokens"),
            completion_tokens=usage_data.get("completion_tokens"),
            total_tokens=usage_data.get("total_tokens"),
        )
        return CompletionResult(content=content, usage=usage)

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                log.warning("Error while closing OpenRouter client")
        self._client = None


_singleton: OpenRouterClient | None = None


def get_openrouter_client() -> OpenRouterClient:
    """Возвращает singleton-инстанс. Закрывается из FastAPI lifespan."""
    global _singleton
    if _singleton is None:
        _singleton = OpenRouterClient()
    return _singleton


async def close_openrouter_client() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.aclose()
    _singleton = None


__all__ = [
    "OpenRouterClient",
    "OpenRouterError",
    "OpenRouterAuthError",
    "StreamingChunk",
    "CompletionResult",
    "get_openrouter_client",
    "close_openrouter_client",
]
