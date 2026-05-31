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
