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
