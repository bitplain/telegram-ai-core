"""Health-check endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.db.session import get_engine
from app.redis.client import ping as redis_ping

log = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    """Лёгкий health-check без обращения к зависимостям."""
    return JSONResponse({"status": "ok", "app": "telegram-ai-core"})


@router.get("/ready")
async def ready() -> JSONResponse:
    """Готовность с проверкой PostgreSQL и Redis."""
    pg_ok = False
    redis_ok = False
    pg_error: str | None = None

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        pg_ok = True
    except Exception as exc:  # noqa: BLE001
        pg_error = exc.__class__.__name__
        log.warning("PG readiness check failed: %s", pg_error)

    try:
        redis_ok = await redis_ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("Redis readiness check failed: %s", exc.__class__.__name__)

    payload = {
        "status": "ok" if (pg_ok and redis_ok) else "degraded",
        "postgres": "ok" if pg_ok else "error",
        "redis": "ok" if redis_ok else "error",
    }
    if pg_error:
        payload["postgres_error"] = pg_error

    status_code = 200 if (pg_ok and redis_ok) else 503
    return JSONResponse(payload, status_code=status_code)


__all__ = ["router"]
