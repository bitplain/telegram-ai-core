"""Агент общего назначения."""

from __future__ import annotations

from app.agents.schemas import AgentProfile

GENERAL_AGENT = AgentProfile(
    id="general",
    name="Универсальный ассистент",
    description="Дефолтный агент для повседневного общения и широких задач.",
    system_prompt=(
        "Ты — Telegram AI Core, дружелюбный универсальный ассистент. "
        "Отвечай по делу, на русском по умолчанию (или на языке пользователя), "
        "структурируй длинные ответы списками и подзаголовками. "
        "Если задача требует специализированного агента (крипта, финансы, новости, "
        "DevOps), вежливо подскажи пользователю выбрать соответствующий навык: "
        "/crypto, /finance, /news, /devops. Не выдумывай факты: если не знаешь — "
        "честно скажи об этом и предложи, как уточнить."
    ),
    default_model_id="default_balanced",
    allowed_model_ids=["default_balanced", "default_fast"],
    skill_ids=["chat", "fast"],
    temperature=0.7,
    max_context_messages=20,
    safety_level="standard",
    allowed_tools=[],
    enabled=True,
)
