"""Orchestrator: связывает agent + skill + model + context + LLM-клиент.

Возвращает асинхронный итератор с дельтами стрима, либо отдаёт
финальный текст для не-стриминговых моделей через тот же интерфейс.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.agents.schemas import AgentProfile
from app.llm.openrouter_client import (
    OpenRouterClient,
    OpenRouterError,
    StreamingChunk,
    get_openrouter_client,
)
from app.models.registry import ModelRegistry, get_model_registry
from app.models.schemas import ModelProfile
from app.skills.schemas import SkillProfile

log = logging.getLogger(__name__)


@dataclass(slots=True)
class OrchestratorPlan:
    """То, что Orchestrator решил сделать: какую модель и температуру использовать."""

    agent: AgentProfile
    skill: SkillProfile
    model: ModelProfile
    temperature: float
    max_tokens: int | None


class Orchestrator:
    """Композиция: выбирает модель и проксирует stream LLM."""

    def __init__(
        self,
        *,
        model_registry: ModelRegistry | None = None,
        client: OpenRouterClient | None = None,
    ) -> None:
        self._model_registry = model_registry or get_model_registry()
        self._client = client or get_openrouter_client()

    def plan(
        self,
        *,
        agent: AgentProfile,
        skill: SkillProfile,
        explicit_model_id: str | None = None,
    ) -> OrchestratorPlan:
        """Выбирает модель и температуру для запроса.

        Алгоритм:
        - Кандидат: explicit_model_id → skill.model_id → agent.default_model_id.
        - Если кандидат не в agent.allowed_model_ids — берём agent.default_model_id
          и логируем warning.
        - Температура: skill.temperature если задана, иначе agent.temperature.
        """
        candidate_id = (
            explicit_model_id or skill.model_id or agent.default_model_id
        )

        if (
            agent.allowed_model_ids
            and candidate_id not in agent.allowed_model_ids
        ):
            log.warning(
                "Model '%s' is not allowed for agent '%s'; using agent default '%s'",
                candidate_id,
                agent.id,
                agent.default_model_id,
            )
            candidate_id = agent.default_model_id

        model = self._model_registry.get(candidate_id)
        temperature = skill.temperature if skill.temperature is not None else agent.temperature
        max_tokens = model.max_output_tokens

        return OrchestratorPlan(
            agent=agent,
            skill=skill,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def run(
        self,
        *,
        plan: OrchestratorPlan,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[StreamingChunk]:
        """Запускает LLM. Yield-ит StreamingChunk-и (для streaming-моделей)
        либо один большой chunk (для non-streaming).

        Бросает ``OpenRouterError`` наружу — handler решает, что показать пользователю.
        """
        model = plan.model
        if model.supports_streaming:
            async for chunk in self._client.stream_chat_completion(
                model=model.model_name,
                messages=messages,
                temperature=plan.temperature,
                max_tokens=plan.max_tokens,
            ):
                yield chunk
        else:
            result = await self._client.chat_completion(
                model=model.model_name,
                messages=messages,
                temperature=plan.temperature,
                max_tokens=plan.max_tokens,
            )
            yield StreamingChunk(content_delta=result.content, finish_reason="stop")


__all__ = ["Orchestrator", "OrchestratorPlan", "OpenRouterError"]
