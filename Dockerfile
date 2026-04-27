FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# System deps: build tools нужны для отдельных колес (asyncpg в исходниках),
# bash — для entrypoint-скриптов, curl — для healthcheck-ов.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        bash \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Сначала проектные метаданные — для кеширования слоя зависимостей.
COPY pyproject.toml README.md /app/
COPY app /app/app

RUN pip install --upgrade pip \
    && pip install -e ".[dev]"

# Остальные файлы поверх (миграции, скрипты, конфиги, тесты, alembic.ini).
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts
COPY tests /app/tests

RUN chmod +x scripts/entrypoint.sh scripts/entrypoint.railway.sh \
    && useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["bash", "scripts/entrypoint.sh"]
