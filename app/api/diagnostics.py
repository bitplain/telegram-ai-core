"""GET /diagnostics — безопасный JSON-снимок состояния приложения.

Эндпоинт никогда не возвращает секреты:
- `telegram_bot_token_set`, `openrouter_api_key_set` — только bool;
- host подключения — без user/password;
- raw `DATABASE_URL` / `REDIS_URL` не отдаются ни при каких условиях.

Опциональная защита: если задана переменная `DIAGNOSTICS_TOKEN`, эндпоинт
проверяет HTTP-заголовок `X-Diagnostics-Token` и отвечает 403 при
несовпадении. По умолчанию защита отключена.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.agents.registry import get_agent_registry
from app.config import get_settings
from app.db.session import get_engine
from app.models.registry import get_model_registry
from app.redis.client import get_redis
from app.skills.registry import get_skill_registry

log = logging.getLogger(__name__)

router = APIRouter(tags=["diagnostics"])


def _safe_host(url: str) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except Exception:  # noqa: BLE001
        return None


def _safe_port(url: str) -> int | None:
    if not url:
        return None
    try:
        return urlparse(url).port
    except Exception:  # noqa: BLE001
        return None


def _safe_db(url: str) -> str | None:
    if not url:
        return None
    try:
        path = urlparse(url).path or ""
        return path.lstrip("/") or None
    except Exception:  # noqa: BLE001
        return None


async def _check_postgres() -> dict[str, Any]:
    settings = get_settings()
    url = settings.database_url_native
    result: dict[str, Any] = {
        "ok": False,
        "host": _safe_host(url),
        "database": _safe_db(url),
        "version": None,
        "error": None,
    }
    if not url:
        result["error"] = "no connection variables configured"
        return result
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT version()"))).scalar_one()
        result["ok"] = True
        if isinstance(row, str):
            # Берём первую строку, чтобы не светить полный server-banner.
            result["version"] = row.splitlines()[0].strip()
    except Exception as exc:  # noqa: BLE001
        result["error"] = exc.__class__.__name__
        log.warning("diagnostics: postgres check failed: %s", result["error"])
    return result


async def _check_redis() -> dict[str, Any]:
    settings = get_settings()
    url = settings.effective_redis_url
    result: dict[str, Any] = {
        "ok": False,
        "host": _safe_host(url),
        "port": _safe_port(url) or (6379 if url else None),
        "version": None,
        "maxmemory_policy": None,
        "error": None,
    }
    if not url:
        result["error"] = "no connection variables configured"
        return result
    client = get_redis()
    if client is None:
        result["error"] = "redis client not initialized"
        return result
    try:
        info_data = await client.info("server")
        result["version"] = info_data.get("redis_version") if isinstance(info_data, dict) else None
        try:
            cfg = await client.config_get("maxmemory-policy")
            if isinstance(cfg, dict):
                result["maxmemory_policy"] = cfg.get("maxmemory-policy")
        except Exception as exc:  # noqa: BLE001
            log.info(
                "diagnostics: CONFIG GET maxmemory-policy unavailable: %s",
                exc.__class__.__name__,
            )
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = exc.__class__.__name__
        log.warning("diagnostics: redis check failed: %s", result["error"])
    return result


async def _schema_version() -> str | None:
    """Текущая версия схемы (alembic head из таблицы alembic_version)."""
    settings = get_settings()
    if not settings.database_url_native:
        return None
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            row = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).first()
        if row is None:
            return None
        return str(row[0])
    except Exception as exc:  # noqa: BLE001
        log.info("diagnostics: schema version unavailable: %s", exc.__class__.__name__)
        return None


def _check_token(provided: str | None) -> None:
    settings = get_settings()
    expected = settings.DIAGNOSTICS_TOKEN
    if not expected:
        return  # охрана отключена
    if not provided or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid diagnostics token",
        )


@router.get("/diagnostics")
async def diagnostics(
    x_diagnostics_token: str | None = Header(default=None, alias="X-Diagnostics-Token"),
) -> JSONResponse:
    _check_token(x_diagnostics_token)

    settings = get_settings()
    skill_registry = get_skill_registry()
    agent_registry = get_agent_registry()
    model_registry = get_model_registry()

    pg_info = await _check_postgres()
    redis_info = await _check_redis()
    schema_version = await _schema_version()

    payload: dict[str, Any] = {
        "app": "telegram-ai-core",
        "app_env": settings.APP_ENV,
        "telegram_mode": settings.TELEGRAM_MODE,
        "telegram_bot_token_set": bool(settings.TELEGRAM_BOT_TOKEN),
        "openrouter_api_key_set": bool(settings.OPENROUTER_API_KEY),
        "openrouter_model": settings.OPENROUTER_MODEL,
        "active_skill_default": skill_registry.default_id,
        "active_agent_default": agent_registry.default_id,
        "active_model_default": model_registry.default_id,
        "postgres": pg_info,
        "redis": redis_info,
        "schema_version": schema_version,
        "connection_sources": settings.connection_sources,
    }
    return JSONResponse(payload)


__all__ = ["router"]
