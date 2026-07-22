#!/bin/bash
# ============================================================
# Scraper Service — Build & Deploy to Synology NAS
#
# Thin wrapper — all logic lives in ../deploy-kit/lib.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="scraper-service"
DISPLAY_NAME="🕸️ Scraper Service"

PRE_BUILD() {
  local CENTRAL_ENV="${DEPLOY_KIT_DIR}/.env.deploy"
  if [ -f "$CENTRAL_ENV" ]; then
    set -a; source "$CENTRAL_ENV"; set +a
    info "Loaded deploy-kit/.env.deploy"
  fi

  # ── Stage scraper source from trading-service (single source of truth) ──
  # The scraper logic lives in trading-service/app/scraper; we copy ONLY that
  # subtree (plus the one broader-app helper it uses — app.utils.text_utils —
  # and the lazycat SDK). The trading engine is deliberately NOT shipped, so
  # this image stays a lean, domain-agnostic scraper. app/ and lazycat/ are
  # gitignored and regenerated on every build.
  local TS="${SCRIPT_DIR}/../trading-service"
  local SDK="${SCRIPT_DIR}/../lazycat-sdk"
  [ -d "${TS}/app/scraper" ] || fail "trading-service/app/scraper not found at ${TS} — clone repos as siblings"
  [ -d "${SDK}/lazycat" ]    || fail "lazycat-sdk/lazycat not found at ${SDK} — clone repos as siblings"

  step "Staging scraper source from trading-service/app/scraper"
  rm -rf "${SCRIPT_DIR}/app" "${SCRIPT_DIR}/lazycat"
  mkdir -p "${SCRIPT_DIR}/app/scraper" "${SCRIPT_DIR}/app/utils"
  : > "${SCRIPT_DIR}/app/__init__.py"
  cp -r "${TS}/app/scraper/." "${SCRIPT_DIR}/app/scraper/"
  # app.utils.text_utils is the only broader-app module the collectors import.
  cp "${TS}/app/utils/text_utils.py" "${SCRIPT_DIR}/app/utils/text_utils.py"
  : > "${SCRIPT_DIR}/app/utils/__init__.py"
  # lazycat SDK: text_utils imports lazycat.llm_json; engines import lazycat.ratelimit
  cp -r "${SDK}/lazycat" "${SCRIPT_DIR}/lazycat"
  # Drop compiled caches so they can't shadow fresh source in the image
  find "${SCRIPT_DIR}/app" "${SCRIPT_DIR}/lazycat" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  find "${SCRIPT_DIR}/app" "${SCRIPT_DIR}/lazycat" -name '*.pyc' -delete 2>/dev/null || true
  ok "scraper source staged (app/scraper + app/utils/text_utils + lazycat)"
}

EXTRA_SSH_SYNC() {
  info "Appending environment overrides to remote .env..."
  ssh "$DEPLOY_SSH_HOST" "echo 'DISABLE_DDG_SEARCH=true' >> '${DEPLOY_COMPOSE_DIR}/.env'"
  ssh "$DEPLOY_SSH_HOST" "echo 'YOUTUBE_COOKIES_FILE=/app/cookies.txt' >> '${DEPLOY_COMPOSE_DIR}/.env'"

  # Inject financial news API keys from vault-service master env
  info "Injecting financial news API keys from vault-service..."
  local VAULT_ENV="${DEPLOY_COMPOSE_ROOT}/vault-service/env/.env"
  local NEWS_KEYS="FINNHUB_API_KEY MARKETAUX_API_KEY NEWSAPI_API_KEY ALPHAVANTAGE_API_KEY POLYGON_API_KEY MASSIVE_API_KEY GNEWS_API_KEY CURRENTS_API_KEY THENEWSAPI_KEY WORLDNEWSAPI_KEY STOCKDATA_API_KEY"
  for KEY in $NEWS_KEYS; do
    ssh "$DEPLOY_SSH_HOST" "grep -q '^${KEY}=' '${VAULT_ENV}' 2>/dev/null && grep '^${KEY}=' '${VAULT_ENV}' >> '${DEPLOY_COMPOSE_DIR}/.env'" 2>/dev/null || true
  done
  ok "Financial news API keys injected"

  info "Syncing cookies.txt..."
  # Touch it remotely so Docker Compose doesn't create a directory if it's missing
  ssh "$DEPLOY_SSH_HOST" "touch '${DEPLOY_COMPOSE_DIR}/cookies.txt'"
  if [ -s "${SCRIPT_DIR}/cookies.txt" ]; then
    cat "${SCRIPT_DIR}/cookies.txt" | ssh "$DEPLOY_SSH_HOST" "cat > '${DEPLOY_COMPOSE_DIR}/cookies.txt'"
    ok "cookies.txt synced"
  else
    warn "cookies.txt is missing or empty. Age-restricted videos will still fail."
  fi
}

source "${SCRIPT_DIR}/../deploy-kit/lib.sh"
