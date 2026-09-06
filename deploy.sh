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
  # app.utils.text_utils is the ONLY module outside app/scraper that the subtree
  # may import. That is not an observation, it is an invariant, enforced by
  # trading-service's tests/unit/test_scraper_subtree_import_closure.py — an
  # allowlist keyed on exactly the copies below. This comment used to assert the
  # same thing as a fact and was false for 27 days: two collectors imported
  # app.utils.async_utils, which ImportErrors in THIS image only. If you add a
  # cp line here, add the module to STAGED_MODULES in that test.
  cp "${TS}/app/utils/text_utils.py" "${SCRIPT_DIR}/app/utils/text_utils.py"
  : > "${SCRIPT_DIR}/app/utils/__init__.py"
  # lazycat SDK: text_utils imports lazycat.llm_json; engines import lazycat.ratelimit
  cp -r "${SDK}/lazycat" "${SCRIPT_DIR}/lazycat"
  # Drop compiled caches so they can't shadow fresh source in the image
  find "${SCRIPT_DIR}/app" "${SCRIPT_DIR}/lazycat" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  find "${SCRIPT_DIR}/app" "${SCRIPT_DIR}/lazycat" -name '*.pyc' -delete 2>/dev/null || true
  ok "scraper source staged (app/scraper + app/utils/text_utils + lazycat)"

  # ── Drift: say which commit is being shipped, and prove the source is clean ──
  # The staged tree is gitignored, so nothing here would otherwise notice that
  # the image is behind trading-service. Measured 2026-09-06: app/scraper matched
  # the last build byte-for-byte while text_utils.py was 66 lines behind, and no
  # signal existed anywhere. Stamp the SOURCE repo's sha, not this repo's — the
  # code being shipped is trading-service's.
  local TS_SHA TS_DIRTY
  TS_SHA=$(git -C "$TS" rev-parse --short HEAD 2>/dev/null || echo unknown)
  TS_DIRTY=$(git -C "$TS" status --porcelain -- app/scraper app/utils/text_utils.py 2>/dev/null)
  if [ -n "$TS_DIRTY" ]; then
    warn "trading-service has UNCOMMITTED scraper changes — this image will contain code that is in no commit:"
    echo "$TS_DIRTY" | sed 's/^/    /'
  fi
  BUILD_ARGS="${BUILD_ARGS} --build-arg GIT_SHA=${TS_SHA} --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  info "Shipping trading-service@${TS_SHA} (verify with: curl -s http://10.0.0.16:8001/health | jq .build)"
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
