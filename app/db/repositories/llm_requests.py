"""Репозиторий llm_requests — журнал обращений к LLM."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LLM_REQUEST_STATUS_ERROR,
    LLM_REQUEST_STATUS_STARTED,
    LLM_REQUEST_STATUS_SUCCESS,
    LLMRequest,
)


class LLMRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_started(
        self,
        *,
        conversation_id: uuid.UUID,
        agent_id: str,
        skill_id: str,
        model_id: str,
        provider: str,
        provider_model_name: str,
    ) -> LLMRequest:
        request = LLMRequest(
            conversation_id=conversation_id,
            agent_id=agent_id,
            skill_id=skill_id,
            model_id=model_id,
            provider=provider,
            provider_model_name=provider_model_name,
            status=LLM_REQUEST_STATUS_STARTED,
        )
        self._session.add(request)
        await self._session.flush()
        return request

    async def mark_success(
        self,
        *,
        request_id: uuid.UUID,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        stmt = (
            update(LLMRequest)
            .where(LLMRequest.id == request_id)
            .values(
                status=LLM_REQUEST_STATUS_SUCCESS,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await self._session.execute(stmt)

    async def mark_error(
        self,
        *,
        request_id: uuid.UUID,
        error: str,
    ) -> None:
        # Обрезаем длинные стектрейсы — БД не должна расти бесконтрольно.
        truncated = error[:4000] if error else error
        stmt = (
            update(LLMRequest)
            .where(LLMRequest.id == request_id)
            .values(
                status=LLM_REQUEST_STATUS_ERROR,
                error=truncated,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await self._session.execute(stmt)

    async def get_last_for_conversation(
        self,
        *,
        conversation_id: uuid.UUID,
    ) -> LLMRequest | None:
        stmt = (
            select(LLMRequest)
            .where(LLMRequest.conversation_id == conversation_id)
            .order_by(LLMRequest.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
