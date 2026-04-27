#!/usr/bin/env bash
# Однократная авто-привязка app-сервиса к Postgres и Redis на Railway.
# Использование: bash scripts/railway-bind.sh
#
# Требования: установлен Railway CLI (`brew install railway` или `npm i -g @railway/cli`),
# выполнен `railway login` и `railway link` в текущем проекте.

set -euo pipefail

readonly SCRIPT_NAME="$(basename "$0")"

err() { printf "[%s] ERROR: %s\n" "$SCRIPT_NAME" "$*" >&2; }
info() { printf "[%s] %s\n" "$SCRIPT_NAME" "$*"; }

# 1. Проверка CLI ----------------------------------------------------------
if ! command -v railway >/dev/null 2>&1; then
    err "Railway CLI is not installed."
    cat <<'HINT'

Install one of:
  brew install railway              # macOS
  npm i -g @railway/cli             # Node-based, любые ОС
  curl -fsSL https://railway.app/install.sh | sh

Then run:
  railway login
  railway link    # выберите нужный project / environment / service
  bash scripts/railway-bind.sh
HINT
    exit 1
fi

# 2. Проверка авторизации --------------------------------------------------
if ! railway whoami >/dev/null 2>&1; then
    err "You are not logged in to Railway."
    cat <<'HINT'

Run:
  railway login
  railway link
  bash scripts/railway-bind.sh
HINT
    exit 1
fi

# 3. Проверка project link -------------------------------------------------
if ! railway status >/dev/null 2>&1; then
    err "This directory is not linked to a Railway project."
    cat <<'HINT'

Run:
  railway link            # выбери project / environment / service
  bash scripts/railway-bind.sh
HINT
    exit 1
fi

# 4. Получаем список сервисов ---------------------------------------------
info "Reading project status..."

STATUS_JSON=""
if STATUS_JSON_RAW="$(railway status --json 2>/dev/null)"; then
    STATUS_JSON="$STATUS_JSON_RAW"
fi

# Пытаемся вычленить имена сервисов через python (он точно есть локально и в CI).
parse_services() {
    python3 - "$STATUS_JSON" <<'PY'
import json
import sys

raw = sys.argv[1] if len(sys.argv) > 1 else ""
if not raw.strip():
    sys.exit(0)
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

# Railway CLI меняет схему между версиями: services могут быть в data["services"]
# либо в data["project"]["services"]["edges"][i]["node"]. Берём осторожно.
candidates: list[str] = []

def collect(obj):
    if isinstance(obj, dict):
        name = obj.get("name") or obj.get("serviceName")
        if isinstance(name, str) and name and name not in candidates:
            candidates.append(name)
        for v in obj.values():
            collect(v)
    elif isinstance(obj, list):
        for v in obj:
            collect(v)

collect(data)
for n in candidates:
    print(n)
PY
}

mapfile -t SERVICES < <(parse_services || true)

if [[ ${#SERVICES[@]} -eq 0 ]]; then
    info "Could not auto-discover services from 'railway status --json'."
    info "Please enter service names manually."
fi

# 5. Подсказываем имена и спрашиваем пользователя --------------------------
choose_service() {
    local kind="$1"
    local pattern="$2"
    local default=""

    for s in "${SERVICES[@]}"; do
        local lower
        lower="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')"
        if [[ "$lower" == *"$pattern"* ]]; then
            default="$s"
            break
        fi
    done

    if [[ ${#SERVICES[@]} -gt 0 ]]; then
        info "Detected services: ${SERVICES[*]}"
    fi

    local prompt="Enter ${kind} service name"
    if [[ -n "$default" ]]; then
        prompt="${prompt} [${default}]"
    fi
    prompt="${prompt}: "

    local answer
    read -r -p "$prompt" answer
    if [[ -z "$answer" && -n "$default" ]]; then
        answer="$default"
    fi
    printf '%s' "$answer"
}

APP_SERVICE="${APP_SERVICE:-}"
PG_SERVICE="${PG_SERVICE:-}"
REDIS_SERVICE="${REDIS_SERVICE:-}"

if [[ -z "$APP_SERVICE" ]]; then
    APP_SERVICE="$(choose_service "app" "telegram")"
fi
if [[ -z "$APP_SERVICE" ]]; then
    err "App service name is required."
    exit 1
fi

if [[ -z "$PG_SERVICE" ]]; then
    PG_SERVICE="$(choose_service "Postgres" "postgres")"
fi
if [[ -z "$PG_SERVICE" ]]; then
    err "Postgres service name is required."
    exit 1
fi

if [[ -z "$REDIS_SERVICE" ]]; then
    REDIS_SERVICE="$(choose_service "Redis" "redis")"
fi
if [[ -z "$REDIS_SERVICE" ]]; then
    err "Redis service name is required."
    exit 1
fi

info "Binding ${APP_SERVICE} → DATABASE_URL=\${{${PG_SERVICE}.DATABASE_URL}}, REDIS_URL=\${{${REDIS_SERVICE}.REDIS_URL}}"

# 6. Проставляем reference variables --------------------------------------
railway variables \
    --service "$APP_SERVICE" \
    --set "DATABASE_URL=\${{${PG_SERVICE}.DATABASE_URL}}" \
    --set "REDIS_URL=\${{${REDIS_SERVICE}.REDIS_URL}}"

info "Done. Final variable list (без значений секретов):"
railway variables --service "$APP_SERVICE" || true

cat <<'NEXT'

[next] Hit "Redeploy" in Railway dashboard, либо `railway up`.
       Затем проверь: GET https://<your-app>.up.railway.app/diagnostics
NEXT
