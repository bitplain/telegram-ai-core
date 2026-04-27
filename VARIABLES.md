# Переменные окружения

Полный справочник по env-переменным `telegram-ai-core`. Все секреты —
только через окружение, в коде/гите их нет. `.env` не коммитится.

## 1. Окружение и сервер

| Переменная | Значение по умолчанию | Описание |
|---|---|---|
| `APP_ENV` | `local` | `local` / `railway` / `production`. На `railway`/`production` обязательны DSN PG и Redis. |
| `LOG_LEVEL` | `INFO` | Уровень логов корневого логгера. |
| `SERVER_HOST` | `0.0.0.0` | Хост, на котором слушает Uvicorn. |
| `SERVER_PORT` | `8000` | Fallback-порт. Используется, если не задан `PORT`. |
| `PORT` | (нет) | Приоритетный порт (Railway/Heroku/etc). |

## 2. Telegram

| Переменная | По умолчанию | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `""` | Токен бота. Если пусто — polling не стартует, FastAPI продолжает работать. |
| `TELEGRAM_MODE` | `polling` | `polling` / `webhook`. На MVP используем `polling`. |
| `TELEGRAM_WEBHOOK_URL` | `""` | URL вебхука, заложен впрок. |
| `TELEGRAM_WEBHOOK_PATH` | `/telegram/webhook` | Путь обработчика вебхука. |
| `TELEGRAM_WEBHOOK_SECRET` | `""` | Telegram secret_token для верификации вебхука. |

## 3. OpenRouter

| Переменная | По умолчанию | Описание |
|---|---|---|
| `OPENROUTER_API_KEY` | `""` | Ключ OpenRouter. Без него бот ответит «ключ не настроен». |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Базовый URL API. |
| `OPENROUTER_MODEL` | `openai/gpt-4.1-mini` | Дефолтная модель. |
| `OPENROUTER_SITE_URL` | `https://example.com` | `HTTP-Referer` для OpenRouter. |
| `OPENROUTER_APP_NAME` | `Telegram AI Core` | `X-Title` для OpenRouter. |

## 4. PostgreSQL — толерантный резолвер DSN

Резолвер `app/config.py` поддерживает несколько источников DSN с понятным
приоритетом. Хватит **любого одного** варианта.

| Приоритет | Переменные | Когда использовать |
|---|---|---|
| 1 | `DATABASE_URL` | Дефолт Railway (`${{Postgres.DATABASE_URL}}`), Heroku, Render. |
| 2 | `POSTGRES_URL` | Альтернативное имя у некоторых хостингов. |
| 3 | `DATABASE_PRIVATE_URL` | Railway-вариант для приватной сети. |
| 4 | `DATABASE_PUBLIC_URL` | Railway-вариант для публичного эндпоинта. |
| 5 | `PGHOST` + `PGPORT` + `PGUSER` + `PGPASSWORD` + `PGDATABASE` | libpq-совместимый набор (Railway default). |
| 6 | `POSTGRES_HOST` + `POSTGRES_PORT` + `POSTGRES_USER` + `POSTGRES_PASSWORD` + `POSTGRES_DB` | Compose-стиль (`docker-compose.yml`). |

Драйверы: `app/db/session.py` и `alembic/env.py` берут DSN с префиксом
`postgresql+asyncpg://` (через `Settings.sqlalchemy_url`); диагностика и
ручные операции — без префикса (`Settings.database_url_native`).

### Авто-привязка через `railway-bind.sh`

Чтобы не клацать Variables в UI, проставь reference-переменные одной командой:

```bash
bash scripts/railway-bind.sh
```

Что делает скрипт:

1. Проверяет, что установлен `railway` CLI и выполнен `railway login` /
   `railway link` для текущего проекта.
2. Через `railway status --json` подбирает имена сервисов Postgres и Redis
   (можно подтвердить или ввести вручную).
3. Выполняет:
   ```bash
   railway variables --service <app-service> \
     --set 'DATABASE_URL=${{<Postgres-service>.DATABASE_URL}}' \
     --set 'REDIS_URL=${{<Redis-service>.REDIS_URL}}'
   ```
4. Печатает финальный список переменных app-сервиса (без значений секретов).

После запуска нужно нажать **Redeploy** в dashboard или выполнить `railway up`.

Если CLI не установлен — `brew install railway` (macOS) или
`npm i -g @railway/cli`.

## 5. Redis — толерантный резолвер DSN

| Приоритет | Переменные | Когда использовать |
|---|---|---|
| 1 | `REDIS_URL` | Дефолт Railway (`${{Redis.REDIS_URL}}`), большинство хостингов. |
| 2 | `REDIS_PRIVATE_URL` | Railway-вариант для приватной сети. |
| 3 | `REDIS_PUBLIC_URL` | Railway-вариант для публичного эндпоинта. |
| 4 | `REDISHOST` + `REDISPORT` + `REDISUSER` + `REDISPASSWORD` | libpq-подобный набор от Railway. |

При старте приложение пытается выполнить
`CONFIG SET maxmemory-policy allkeys-lru`. Если managed-плагин запрещает
`CONFIG SET` — лог пишет warning, но приложение не падает.

## 6. Лимиты и таймауты

| Переменная | По умолчанию | Описание |
|---|---|---|
| `LLM_TIMEOUT_SECONDS` | `120` | Тайм-аут стриминга OpenRouter. |
| `RATE_LIMIT_MESSAGES` | `30` | Лимит сообщений на пользователя. |
| `RATE_LIMIT_WINDOW_SECONDS` | `3600` | Окно рейта. |

## 7. Renderer (Telegram)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `TELEGRAM_DRAFT_MIN_INTERVAL_MS` | `500` | Минимальный интервал между `editMessageText`. |
| `TELEGRAM_MIN_DELTA_CHARS` | `24` | Минимальный прирост текста перед редактом. |
| `TELEGRAM_CHAT_ACTION_INTERVAL_SECONDS` | `4.0` | Не чаще одного `sendChatAction` за интервал. |
| `TELEGRAM_MESSAGE_MAX_CHARS` | `3900` | Длина чанка для сплиттера. |

## 8. Diagnostics

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DIAGNOSTICS_TOKEN` | `""` | Если задано — `GET /diagnostics` требует заголовок `X-Diagnostics-Token: <value>`, иначе 403. По умолчанию эндпоинт открыт. |

`GET /diagnostics` возвращает JSON со статусом `postgres`/`redis`, версиями
серверов, `schema_version` (Alembic head), `connection_sources` и набором
boolean-флагов про токены. Никаких секретов / raw-URL не отдаётся.

Пример:

```bash
curl https://<your-app>.up.railway.app/diagnostics

# C защитой:
curl -H "X-Diagnostics-Token: <secret>" https://<your-app>.up.railway.app/diagnostics
```

## 9. Безопасность

- Любые `*_TOKEN`, `*_KEY`, `*_PASSWORD`, `*_SECRET` фильтруются в логах
  (`app/logging_config.py`).
- DSN с паролем перед печатью маскируется (`mask_url_password` в
  `app/config.py`).
- `/diagnostics` отдаёт только bool-флаги для чувствительных полей.
