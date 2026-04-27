"""Pydantic-схемы для агентов."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SafetyLevel = Literal["low", "standard", "high"]


class AgentProfile(BaseModel):
    """Описание агента — профиль маршрутизации с system_prompt и набором skill-ов.

    На MVP агенты — это in-memory профили. В будущем — потенциально записи в БД.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""
    system_prompt: str
    default_model_id: str = "default_balanced"
    allowed_model_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_context_messages: int = Field(default=20, ge=1, le=200)
    safety_level: SafetyLevel = "standard"
    allowed_tools: list[str] = Field(default_factory=list)
    enabled: bool = True
    show_in_agent_menu: bool = True
