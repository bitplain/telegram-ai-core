"""Orchestrator: связывает agent + skill + model + context + LLM-клиент.

Возвращает асинхронный итератор с дельтами стрима, либо отдаёт
финальный текст для не-стриминговых моделей через тот же интерфейс.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.agents.schemas import AgentProfile
from app.config import get_settings
from app.core.services.user_agent_settings import UserAgentSettingsService
from app.core.settings_store import get_settings_store
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
    custom_prompt_used: bool = False


class Orchestrator:
    """Композиция: выбирает модель и проксирует stream LLM."""

    def __init__(
        self,
        *,
        model_registry: ModelRegistry | None = None,
        client: OpenRouterClient | None = None,
        agent_settings_service: UserAgentSettingsService | None = None,
    ) -> None:
        self._model_registry = model_registry or get_model_registry()
        self._client = client or get_openrouter_client()
        self._agent_settings_service = agent_settings_service

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

    async def plan_async(
        self,
        *,
        agent: AgentProfile,
        skill: SkillProfile,
        explicit_model_id: str | None = None,
        telegram_user_id: int | None = None,
    ) -> OrchestratorPlan:
        """То же, что ``plan``, но дополнительно применяет model_override
        из ``app_settings`` (если admin переопределил модель через /settings).

        Override меняет только ``ModelProfile.model_name`` (OpenRouter slug),
        остальные поля профиля сохраняются.
        """
        base_plan = self.plan(
            agent=agent, skill=skill, explicit_model_id=explicit_model_id
        )
        if telegram_user_id is not None:
            base_plan = await self.apply_user_agent_settings(
                base_plan=base_plan,
                telegram_user_id=telegram_user_id,
            )
        store = get_settings_store()
        override = await store.get_model_override(base_plan.model.id)
        if not override:
            return base_plan
        # ModelProfile — frozen pydantic-модель; используем model_copy для
        # точечной замены model_name.
        try:
            new_model = base_plan.model.model_copy(update={"model_name": override})
        except Exception:  # noqa: BLE001
            log.exception(
                "Failed to apply model_override '%s' for '%s'; using default",
                override,
                base_plan.model.id,
            )
            return base_plan
        return OrchestratorPlan(
            agent=base_plan.agent,
            skill=base_plan.skill,
            model=new_model,
            temperature=base_plan.temperature,
            max_tokens=base_plan.max_tokens,
            custom_prompt_used=base_plan.custom_prompt_used,
        )

    async def apply_user_agent_settings(
        self,
        *,
        base_plan: OrchestratorPlan,
        telegram_user_id: int,
    ) -> OrchestratorPlan:
        service = self._agent_settings_service or UserAgentSettingsService()
        settings = await service.get_effective_settings(
            telegram_user_id=telegram_user_id,
            agent_id=base_plan.agent.id,
        )
        return OrchestratorPlan(
            agent=base_plan.agent,
            skill=base_plan.skill,
            model=settings.effective_model,
            temperature=base_plan.temperature,
            max_tokens=settings.effective_model.max_output_tokens,
            custom_prompt_used=settings.custom_prompt_used,
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
        api_key = (get_settings().OPENROUTER_API_KEY or "").strip() or None

        if model.supports_streaming:
            async for chunk in self._client.stream_chat_completion(
                model=model.model_name,
                messages=messages,
                temperature=plan.temperature,
                max_tokens=plan.max_tokens,
                api_key_override=api_key,
            ):
                yield chunk
        else:
            result = await self._client.chat_completion(
                model=model.model_name,
                messages=messages,
                temperature=plan.temperature,
                max_tokens=plan.max_tokens,
                api_key_override=api_key,
            )
            yield StreamingChunk(content_delta=result.content, finish_reason="stop")


__all__ = ["Orchestrator", "OrchestratorPlan", "OpenRouterError"]
