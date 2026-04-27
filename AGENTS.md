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
4. `docker compose exec -T app pytest -q` — все тесты должны проходить.

## MVP-ограничения, которые мы сознательно держим

- Tools для агентов архитектурно заложены (`AgentProfile.allowed_tools`), но не реализованы.
- Нет pgvector / RAG / managed bots / долговременной memory.
- Webhook-маршрут есть, но MVP проверяется через polling.
