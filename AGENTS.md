# AGENTS.md

Правила работы AI-ассистентов с этим репозиторием.

## Общие принципы

- Думаем и пишем **на русском**. Имена файлов, классов, функций, переменных — на английском.
- Это **production-oriented** проект, не демо. Никаких TODO, заглушек, частичных патчей.
- Любое изменение должно оставлять репозиторий в работоспособном состоянии: `docker compose up` стартует, `/health` отдаёт 200, `pytest` зелёный.
- Не использовать тяжёлые агентные фреймворки: **никаких LangChain, CrewAI, AutoGen** и т.п. Только httpx, FastAPI, aiogram, SQLAlchemy.

## Безопасность

- **Не хардкодить секреты** в коде. Все ключи и пароли — только через переменные окружения.
- **Не коммитить `.env`** (он в `.gitignore`). Менять только `.env.example`.
- Не логировать значения `*token*`, `*key*`, `*password*`, `*secret*` — фильтр в `app/logging_config.py` маскирует их автоматически, но и в коде не передавайте такие значения в `extra={...}`.
- Маскировать пароль в `DATABASE_URL` / `REDIS_URL` перед логированием.

## Структура и слои

- Перед изменением — прочитать структуру (`app/`, `alembic/`, `tests/`, `scripts/`).
- Не смешивать в одном файле:
  - Telegram-handlers (`app/bot/handlers/`),
  - DB (`app/db/`, `app/db/repositories/`),
  - Skills/Agents/Models (`app/skills/`, `app/agents/`, `app/models/`),
  - LLM (`app/llm/`),
  - оркестрацию (`app/core/`).
- Новый skill / agent / model — это новый файл/запись в registry, а не правка обработчика сообщений.
- Storage — только асинхронный SQLAlchemy + Alembic. Прямой `Base.metadata.create_all` — запрещён, схему меняем через миграции.

## Telegram

- В renderer-е используем `sendMessageDraft` → `editMessageText` → fallback `sendMessage`. Throttle 400–700 мс, минимальный прирост текста ≥ 24 символа, `sendChatAction` не чаще раз в 4 секунды.
- В group/supergroup — сразу fallback (никаких драфтов).
- Длинные сообщения бьём по 3900 символов через `app/utils/text_splitter.py`.

## После изменений

1. `docker compose up -d --build`
2. `curl http://localhost:8000/health` — должен быть 200.
3. `curl http://localhost:8000/ready` — должен быть 200, если PG и Redis подняты.
4. `curl http://localhost:8000/diagnostics` — JSON со статусом PG/Redis, источниками подключения и `schema_version` (без секретов).
5. `docker compose exec -T app pytest -q` — все тесты должны проходить.

## Railway-обвязка

- Конфиг толерантен к набору переменных (`DATABASE_URL` / `POSTGRES_URL` /
  `DATABASE_PRIVATE_URL` / `DATABASE_PUBLIC_URL` / `PGHOST+...`,
  и `REDIS_URL` / `REDIS_PRIVATE_URL` / `REDIS_PUBLIC_URL` / `REDISHOST+...`).
  Подробности — `VARIABLES.md`.
- Для однократной привязки app-сервиса к Postgres/Redis есть
  `bash scripts/railway-bind.sh` — он через Railway CLI проставляет нужные
  reference variables.
- `GET /diagnostics` — единая точка для проверки прод-конфигурации (статус
  PG/Redis, версии, `schema_version`, `connection_sources`). Если задан
  `DIAGNOSTICS_TOKEN` — нужен заголовок `X-Diagnostics-Token`.
- `scripts/entrypoint.railway.sh` сначала запускает
  `scripts/railway_diagnose.py`, который печатает безопасную сводку (без
  паролей) и валит старт с понятной инструкцией, если переменные не заданы.

## Admin /settings и runtime-настройки

- Команда `/settings` доступна только админам (`ADMIN_TELEGRAM_USER_IDS` —
  CSV Telegram user-id). Фильтр — `app/bot/filters/admin.py`.
- Состояние диалогов с ботом (FSM) — `MemoryStorage` в `Dispatcher`. Хватает,
  пока бот однопроцессный; миграция на Redis-storage — следующим этапом.
- `app/core/settings_store.py` — единая точка доступа к runtime-настройкам в БД:
  - `model_override.<model_id>` (override OpenRouter slug-а для конкретного
    `ModelProfile`),
  - прочие ключи (например заглушка Yandex) — **не** OpenRouter: `OPENROUTER_API_KEY`
    задаётся **только** в ENV.
- Кеш настроек — Redis (`app_settings:v1:*`, TTL 60s). При недоступном Redis —
  каждый вызов идёт в БД, без падений.
- `app/llm/openrouter_models.py` — список моделей OpenRouter с кешем 12h
  (`openrouter:models:v1`). Эндпоинт `/api/v1/models` публичный, без Authorization.
- `Orchestrator.plan_async` применяет `model_override` поверх
  `ModelRegistry.get(...)`. Sync `plan(...)` сохранён для совместимости.
- `Orchestrator.run` передаёт в LLM-клиент ключ из `OPENROUTER_API_KEY` (ENV)
  через kwarg `api_key_override`. `_build_headers` не логирует ключ.

При добавлении новых runtime-настроек:

- Класть их в `app_settings` (key/value/is_encrypted), не в новый ENV.
- Проводить через `SettingsStore` (всегда async, всегда с инвалидацией Redis).
- Не светить значения секретов в логах — только маскированный вид.

## MVP-ограничения, которые мы сознательно держим

- Tools для агентов архитектурно заложены (`AgentProfile.allowed_tools`), но не реализованы.
- Нет pgvector / RAG / managed bots; краткая память — таблица `memories` + команды бота.
- Webhook: при `TELEGRAM_MODE=webhook` нужны `PUBLIC_API_URL` и `TELEGRAM_WEBHOOK_SECRET`;
  для локальной разработки чаще используют polling.
