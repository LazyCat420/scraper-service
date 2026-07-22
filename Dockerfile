# ============================================================
# Scraper Service — Docker Build
# ============================================================
# General-purpose scraping microservice. Exposes HTTP API on :8001.
#
# `app/` and `lazycat/` are NOT committed — deploy.sh copies them from
# trading-service/app (scraper subtree) and lazycat-sdk at build time, so the
# scraper logic has a single source of truth in trading-service. To build by
# hand, run deploy.sh's PRE_BUILD copy steps first (see deploy.sh).
# ============================================================

FROM python:3.11-slim AS deps

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Production runner ─────────────────────────────────────────
FROM python:3.11-slim AS runner
WORKDIR /app

# Non-root user
RUN groupadd --system --gid 1001 appgrp \
    && useradd --system --uid 1001 --gid appgrp -m -d /home/appusr appusr \
    && mkdir -p /app/logs && chown -R appusr:appgrp /app/logs

# Python venv
COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# wget (healthcheck) + curl + Playwright Chromium system deps (as root)
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget curl \
    && DEBIAN_FRONTEND=noninteractive playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# ── Service source (build-copied by deploy.sh PRE_BUILD) ──────
COPY app/ ./app/
COPY lazycat/ ./lazycat/
COPY scraper_main.py ./scraper_main.py

RUN chown -R appusr:appgrp /app

ENV PYTHONPATH="/app"
ENV HOST="0.0.0.0"
ENV PORT="8001"

USER appusr

# Pre-bake Chromium into appusr's cache (~/.cache/ms-playwright)
RUN playwright install chromium

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget --no-verbose --tries=1 -O /dev/null http://localhost:8001/health || exit 1

# 2 workers: each uvicorn worker boots its own Playwright/Chromium via
# session_manager, so worker count multiplies browser memory. 2 balances
# throughput against the NAS memory budget (see docker-compose.yml limit).
CMD ["uvicorn", "scraper_main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
