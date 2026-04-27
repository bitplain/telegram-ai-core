"""Pydantic-схемы для skill-ов (профилей маршрутизации поверх агентов)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SkillProfile(BaseModel):
    """Skill — короткий ярлык режима общения, который пользователь выбирает командой.

    Skill ссылается на agent_id и опционально переопределяет model_id и temperature.
    Команды и keywords — для авто-маршрутизации в SkillRouter.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""
    agent_id: str
    model_id: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    trigger_commands: list[str] = Field(default_factory=list)
    trigger_keywords: list[str] = Field(default_factory=list)
    enabled: bool = True
