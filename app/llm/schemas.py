"""Pydantic-схемы LLM-уровня."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    """Сообщение в формате chat completions."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str


class ChatCompletionRequest(BaseModel):
    """Запрос к OpenRouter chat/completions."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    stream: bool = True
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class StreamUsage(BaseModel):
    """Опциональные метрики использования токенов."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


__all__ = ["ChatMessage", "ChatCompletionRequest", "StreamUsage", "Role"]
