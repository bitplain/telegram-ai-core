#!/usr/bin/env bash
# Локальный entrypoint (docker compose).
# Ждёт готовности PG и Redis, прогоняет alembic миграции и стартует Uvicorn.

set -euo pipefail

echo "[entrypoint] APP_ENV=${APP_ENV:-local}"
echo "[entrypoint] TELEGRAM_MODE=${TELEGRAM_MODE:-polling}"
echo "[entrypoint] OPENROUTER_MODEL=${OPENROUTER_MODEL:-openai/gpt-4.1-mini}"
echo "[entrypoint] PORT=${PORT:-${SERVER_PORT:-8000}}"

python scripts/wait-for-services.py

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head

PORT_TO_USE="${PORT:-${SERVER_PORT:-8000}}"
HOST_TO_USE="${SERVER_HOST:-0.0.0.0}"

echo "[entrypoint] starting uvicorn on ${HOST_TO_USE}:${PORT_TO_USE}"
exec uvicorn app.main:app --host "${HOST_TO_USE}" --port "${PORT_TO_USE}"
