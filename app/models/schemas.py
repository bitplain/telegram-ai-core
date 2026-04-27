"""Pydantic-схемы для LLM ModelProfile."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModelTier = Literal["cheap", "balanced", "premium"]


class ModelProfile(BaseModel):
    """Описание LLM-модели в registry.

    На MVP мы маршрутизируем все модели через OpenRouter, поэтому provider
    зафиксирован, а ``model_name`` — это OpenRouter slug
    (например, "openai/gpt-4.1-mini").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    display_name: str
    description: str = ""
    provider: str = "openrouter"
    model_name: str
    tier: ModelTier = "balanced"
    supports_streaming: bool = True
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    enabled: bool = True
