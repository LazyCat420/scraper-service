# ============================================================
# Scraper Service — Docker Build
# ============================================================
# General-purpose scraping microservice.
# Exposes HTTP API on port 8001.
#
# Build:
#   cd sun/scraper-service
#   docker build -t scraper-service .
# ============================================================

FROM python:3.11-slim AS deps

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Production runner ─────────────────────────────────────────
FROM python:3.11-slim AS runner
WORKDIR /app

# Install wget for healthcheck + deps for playwright/yt-dlp
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --system --gid 1001 appgrp \
    && useradd --system --uid 1001 --gid appgrp -m -d /home/appusr appusr

# Create logs directory
RUN mkdir -p /app/logs && chown -R appusr:appgrp /app/logs

# ── Copy Python venv ──────────────────────────────────────────
COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── Copy service source ──────────────────────────────────────
COPY app/ ./app/

RUN chown -R appusr:appgrp /app

ENV PYTHONPATH="/app"
ENV HOST="0.0.0.0"
ENV PORT="8001"

USER appusr

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget --spider -q http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
