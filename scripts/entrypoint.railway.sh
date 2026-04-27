#!/usr/bin/env bash
# Railway entrypoint. На Railway PG и Redis — managed-сервисы,
# готовы к моменту старта приложения. wait-for-services не требуется.
#
# Перед стартом запускаем scripts/railway_diagnose.py: он подгружает Settings,
# распознаёт любой поддерживаемый формат env-переменных Postgres/Redis
# (DATABASE_URL, POSTGRES_URL, DATABASE_PRIVATE_URL, DATABASE_PUBLIC_URL,
# PGHOST+PGPORT+..., REDIS_URL, REDIS_PRIVATE_URL, REDIS_PUBLIC_URL,
# REDISHOST+...), печатает безопасную сводку (без паролей) и падает с
# понятной инструкцией, если ничего не найдено.

set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
export PYTHONPATH="${PYTHONPATH:-/app}"

"${PYTHON_BIN}" scripts/railway_diagnose.py

if [[ -z "${TELEGRAM_MODE:-}" ]]; then
    export TELEGRAM_MODE="polling"
fi

echo "[entrypoint.railway] running alembic upgrade head..."
alembic upgrade head

PORT_TO_USE="${PORT:-8000}"

echo "[entrypoint.railway] starting uvicorn on 0.0.0.0:${PORT_TO_USE}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT_TO_USE}"
