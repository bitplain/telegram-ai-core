"""Service layer for user-scoped agent settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agents.registry import AgentRegistry, get_agent_registry
from app.agents.schemas import AgentProfile
from app.config import get_settings
from app.db.models import UserAgentSetting
from app.db.repositories.user_agent_settings import UserAgentSettingsRepository
from app.db.session import session_scope
from app.models.registry import ModelRegistry, get_model_registry
from app.models.schemas import ModelProfile


class UnknownAgentError(ValueError):
    pass


class UnknownModelError(ValueError):
    pass


class EmptyAgentPromptError(ValueError):
    pass


class AgentPromptTooLongError(ValueError):
    pass


class AgentSettingsRepositoryProtocol(Protocol):
    async def get_settings(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting | None: ...

    async def upsert_custom_prompt(
        self, telegram_user_id: int, agent_id: str, custom_prompt: str
    ) -> UserAgentSetting: ...

    async def reset_custom_prompt(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting: ...

    async def upsert_model_id(
        self, telegram_user_id: int, agent_id: str, model_id: str
    ) -> UserAgentSetting: ...

    async def list_user_settings(self, telegram_user_id: int) -> list[UserAgentSetting]: ...


@dataclass(slots=True, frozen=True)
class EffectiveAgentSettings:
    agent: AgentProfile
    default_prompt: str
    custom_prompt: str | None
    effective_prompt: str
    default_model: ModelProfile
    selected_model: ModelProfile | None
    effective_model: ModelProfile
    custom_prompt_used: bool


class UserAgentSettingsService:
    """Validates and resolves per-user agent settings."""

    def __init__(
        self,
        *,
        repository: AgentSettingsRepositoryProtocol | None = None,
        agent_registry: AgentRegistry | None = None,
        model_registry: ModelRegistry | None = None,
        prompt_max_length: int | None = None,
        settings_store=None,
    ) -> None:
        self._repository = repository
        self._agent_registry = agent_registry or get_agent_registry()
        self._model_registry = model_registry or get_model_registry()
        self._settings_store = settings_store
        self._prompt_max_length = (
            prompt_max_length
            if prompt_max_length is not None
            else get_settings().AGENT_PROMPT_MAX_LENGTH
        )

    def list_enabled_agents(self) -> list[AgentProfile]:
        return self._agent_registry.list_enabled()

    def list_enabled_models(self) -> list[ModelProfile]:
        return self._model_registry.list_enabled()

    async def list_favorite_model_slugs(self) -> list[str]:
        from app.core.settings_store import get_settings_store

        store = self._settings_store or get_settings_store()
        return await store.list_openrouter_favorite_models()

    async def list_selectable_model_slugs(self) -> list[str]:
        favorites = await self.list_favorite_model_slugs()
        if favorites:
            return favorites
        return [model.model_name for model in self._model_registry.list_enabled()]

    async def get_effective_settings(
        self, *, telegram_user_id: int, agent_id: str
    ) -> EffectiveAgentSettings:
        agent = self._require_agent(agent_id)
        row = await self._get_row(telegram_user_id, agent.id)

        custom_prompt = (row.custom_prompt or "").strip() if row else ""
        default_model = self._model_registry.get(agent.default_model_id)
        selected_model: ModelProfile | None = None
        if row and row.model_id:
            selected_model = await self._resolve_model(row.model_id, default_model)

        return EffectiveAgentSettings(
            agent=agent,
            default_prompt=agent.system_prompt,
            custom_prompt=custom_prompt or None,
            effective_prompt=custom_prompt or agent.system_prompt,
            default_model=default_model,
            selected_model=selected_model,
            effective_model=selected_model or default_model,
            custom_prompt_used=bool(custom_prompt),
        )

    async def set_custom_prompt(
        self, *, telegram_user_id: int, agent_id: str, custom_prompt: str
    ) -> UserAgentSetting:
        agent = self._require_agent(agent_id)
        prompt = custom_prompt.strip()
        if not prompt:
            raise EmptyAgentPromptError("custom prompt is empty")
        if len(prompt) > self._prompt_max_length:
            raise AgentPromptTooLongError("custom prompt is too long")
        return await self._with_repository(
            lambda repo: repo.upsert_custom_prompt(telegram_user_id, agent.id, prompt)
        )

    async def reset_custom_prompt(
        self, *, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting:
        agent = self._require_agent(agent_id)
        return await self._with_repository(
            lambda repo: repo.reset_custom_prompt(telegram_user_id, agent.id)
        )

    async def set_model_id(
        self, *, telegram_user_id: int, agent_id: str, model_id: str
    ) -> UserAgentSetting:
        agent = self._require_agent(agent_id)
        default_model = self._model_registry.get(agent.default_model_id)
        model = await self._resolve_model(model_id, default_model)
        if model is None:
            raise UnknownModelError(model_id)
        return await self._with_repository(
            lambda repo: repo.upsert_model_id(telegram_user_id, agent.id, model_id)
        )

    async def _resolve_model(
        self, model_id_or_slug: str, default_model: ModelProfile
    ) -> ModelProfile | None:
        model = self._model_registry.get_or_none(model_id_or_slug)
        if model is not None and model.enabled:
            return model
        if "/" not in model_id_or_slug:
            return None
        if model_id_or_slug not in await self.list_favorite_model_slugs():
            return None
        return default_model.model_copy(
            update={
                "id": model_id_or_slug,
                "display_name": model_id_or_slug,
                "model_name": model_id_or_slug,
            }
        )

    async def list_user_settings(self, telegram_user_id: int) -> list[UserAgentSetting]:
        return await self._with_repository(
            lambda repo: repo.list_user_settings(telegram_user_id)
        )

    def _require_agent(self, agent_id: str) -> AgentProfile:
        agent = self._agent_registry.get_or_none(agent_id)
        if agent is None or not agent.enabled:
            raise UnknownAgentError(agent_id)
        return agent

    async def _get_row(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting | None:
        return await self._with_repository(
            lambda repo: repo.get_settings(telegram_user_id, agent_id)
        )

    async def _with_repository(self, callback):
        if self._repository is not None:
            return await callback(self._repository)
        async with session_scope() as session:
            repo = UserAgentSettingsRepository(session)
            return await callback(repo)


# Backward-compatible alias for tests/older imports.
AgentSettingsService = UserAgentSettingsService


__all__ = [
    "AgentPromptTooLongError",
    "AgentSettingsService",
    "EffectiveAgentSettings",
    "EmptyAgentPromptError",
    "UnknownAgentError",
    "UnknownModelError",
    "UserAgentSettingsService",
]
