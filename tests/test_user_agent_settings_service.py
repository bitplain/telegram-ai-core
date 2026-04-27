"""Тесты сервиса user-scoped настроек агентов."""

from __future__ import annotations

import pytest

from app.core.services.user_agent_settings import (
    AgentPromptTooLongError,
    EmptyAgentPromptError,
    UnknownAgentError,
    UnknownModelError,
    UserAgentSettingsService,
)
from app.db.models import UserAgentSetting


class _MemoryUserAgentSettingsRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[int, str], UserAgentSetting] = {}

    async def get_settings(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting | None:
        return self.rows.get((telegram_user_id, agent_id))

    async def upsert_custom_prompt(
        self, telegram_user_id: int, agent_id: str, custom_prompt: str
    ) -> UserAgentSetting:
        row = self.rows.get((telegram_user_id, agent_id))
        if row is None:
            row = UserAgentSetting(
                telegram_user_id=telegram_user_id,
                agent_id=agent_id,
                custom_prompt=custom_prompt,
            )
            self.rows[(telegram_user_id, agent_id)] = row
        else:
            row.custom_prompt = custom_prompt
        return row

    async def reset_custom_prompt(
        self, telegram_user_id: int, agent_id: str
    ) -> UserAgentSetting:
        row = self.rows.setdefault(
            (telegram_user_id, agent_id),
            UserAgentSetting(telegram_user_id=telegram_user_id, agent_id=agent_id),
        )
        row.custom_prompt = None
        return row

    async def upsert_model_id(
        self, telegram_user_id: int, agent_id: str, model_id: str
    ) -> UserAgentSetting:
        row = self.rows.setdefault(
            (telegram_user_id, agent_id),
            UserAgentSetting(telegram_user_id=telegram_user_id, agent_id=agent_id),
        )
        row.model_id = model_id
        return row

    async def list_user_settings(self, telegram_user_id: int) -> list[UserAgentSetting]:
        return [
            row
            for (uid, _), row in self.rows.items()
            if uid == telegram_user_id
        ]


@pytest.fixture()
def repo() -> _MemoryUserAgentSettingsRepository:
    return _MemoryUserAgentSettingsRepository()


@pytest.fixture()
def service(repo: _MemoryUserAgentSettingsRepository) -> UserAgentSettingsService:
    return UserAgentSettingsService(repository=repo, prompt_max_length=20)


@pytest.mark.asyncio
async def test_effective_settings_fallback_to_default_prompt_and_model(
    service: UserAgentSettingsService,
) -> None:
    result = await service.get_effective_settings(
        telegram_user_id=100,
        agent_id="crypto",
    )

    assert result.agent.id == "crypto"
    assert result.custom_prompt is None
    assert result.effective_prompt == result.default_prompt
    assert result.selected_model is None
    assert result.effective_model.id == result.default_model.id


@pytest.mark.asyncio
async def test_create_and_update_custom_prompt(
    service: UserAgentSettingsService,
) -> None:
    await service.set_custom_prompt(
        telegram_user_id=100,
        agent_id="crypto",
        custom_prompt="Первый prompt",
    )
    await service.set_custom_prompt(
        telegram_user_id=100,
        agent_id="crypto",
        custom_prompt="Новый prompt",
    )

    result = await service.get_effective_settings(
        telegram_user_id=100,
        agent_id="crypto",
    )
    assert result.custom_prompt == "Новый prompt"
    assert result.effective_prompt == "Новый prompt"


@pytest.mark.asyncio
async def test_reset_custom_prompt_restores_default(
    service: UserAgentSettingsService,
) -> None:
    await service.set_custom_prompt(
        telegram_user_id=100,
        agent_id="crypto",
        custom_prompt="Custom",
    )
    await service.reset_custom_prompt(telegram_user_id=100, agent_id="crypto")

    result = await service.get_effective_settings(
        telegram_user_id=100,
        agent_id="crypto",
    )
    assert result.custom_prompt is None
    assert result.effective_prompt == result.default_prompt


@pytest.mark.asyncio
async def test_set_model_override(
    service: UserAgentSettingsService,
) -> None:
    await service.set_model_id(
        telegram_user_id=100,
        agent_id="crypto",
        model_id="default_fast",
    )

    result = await service.get_effective_settings(
        telegram_user_id=100,
        agent_id="crypto",
    )
    assert result.selected_model is not None
    assert result.selected_model.id == "default_fast"
    assert result.effective_model.id == "default_fast"


@pytest.mark.asyncio
async def test_invalid_agent_id_raises(service: UserAgentSettingsService) -> None:
    with pytest.raises(UnknownAgentError):
        await service.get_effective_settings(
            telegram_user_id=100,
            agent_id="missing-agent",
        )


@pytest.mark.asyncio
async def test_invalid_model_id_raises(service: UserAgentSettingsService) -> None:
    with pytest.raises(UnknownModelError):
        await service.set_model_id(
            telegram_user_id=100,
            agent_id="crypto",
            model_id="missing-model",
        )


@pytest.mark.asyncio
async def test_empty_prompt_rejected(service: UserAgentSettingsService) -> None:
    with pytest.raises(EmptyAgentPromptError):
        await service.set_custom_prompt(
            telegram_user_id=100,
            agent_id="crypto",
            custom_prompt="   ",
        )


@pytest.mark.asyncio
async def test_too_long_prompt_rejected(service: UserAgentSettingsService) -> None:
    with pytest.raises(AgentPromptTooLongError):
        await service.set_custom_prompt(
            telegram_user_id=100,
            agent_id="crypto",
            custom_prompt="x" * 21,
        )


def test_registry_lists_are_used(service: UserAgentSettingsService) -> None:
    agents = service.list_enabled_agents()
    models = service.list_enabled_models()

    assert {agent.id for agent in agents} >= {"general", "crypto"}
    assert {model.id for model in models} >= {"default_fast", "default_balanced"}
