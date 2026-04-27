#!/usr/bin/env bash
# Railway entrypoint. На Railway PG и Redis — managed-сервисы,
# готовы к моменту старта приложения. wait-for-services не требуется.
# Печатаем только не-секретные параметры окружения.

set -euo pipefail

echo "[entrypoint.railway] APP_ENV=${APP_ENV:-railway}"
echo "[entrypoint.railway] TELEGRAM_MODE=${TELEGRAM_MODE:-polling}"
echo "[entrypoint.railway] OPENROUTER_MODEL=${OPENROUTER_MODEL:-openai/gpt-4.1-mini}"
echo "[entrypoint.railway] PORT=${PORT:-8000}"

if [[ -z "${TELEGRAM_MODE:-}" ]]; then
    export TELEGRAM_MODE="polling"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "[entrypoint.railway] ERROR: DATABASE_URL is empty. Configure Postgres reference variable." >&2
    exit 1
fi

if [[ -z "${REDIS_URL:-}" ]]; then
    echo "[entrypoint.railway] ERROR: REDIS_URL is empty. Configure Redis reference variable." >&2
    exit 1
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    echo "[entrypoint.railway] WARNING: TELEGRAM_BOT_TOKEN is empty — polling will not start." >&2
fi

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo "[entrypoint.railway] WARNING: OPENROUTER_API_KEY is empty — bot will reply with 'key not configured'." >&2
fi

echo "[entrypoint.railway] running alembic upgrade head..."
alembic upgrade head

PORT_TO_USE="${PORT:-8000}"

echo "[entrypoint.railway] starting uvicorn on 0.0.0.0:${PORT_TO_USE}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT_TO_USE}"
