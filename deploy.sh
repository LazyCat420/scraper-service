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
}

source "${SCRIPT_DIR}/../deploy-kit/lib.sh"
