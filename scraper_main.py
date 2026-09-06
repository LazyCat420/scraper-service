"""
scraper-service — General-purpose scraping microservice (standalone).

Domain-agnostic. No trading logic, no financial context — all domain knowledge
stays in the calling service. Exposes HTTP, Playwright and crawl4ai
scraping engines plus the Reddit / YouTube / News / social collectors.

The scraper source of truth lives in `trading-service/app/scraper/`; this repo's
`app/` and `lazycat/` trees are copied in at build time by deploy.sh (the same
build-time-mirror pattern lazy-agent-service uses), so there is exactly one copy
of the scraper logic to maintain. This entrypoint mounts ONLY the scraper
routers — none of the trading engine.

Runs on :8001 (the historical scraper-service port). Callers point their
SCRAPER_SERVICE_URL here.
"""

import logging
import os
from contextlib import asynccontextmanager

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException

from app.scraper.api.routes import collect, health, scrape, stream
from app.scraper.core.session_manager import session_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("scraper-service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the scraper service.

    session_manager also lazy-inits on first use, so a startup failure here can
    never wedge an external /scrape request — we log and continue rather than
    aborting boot.
    """
    try:
        await session_manager.startup()
        logger.info("scraper-service started (session_manager ready)")
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"session_manager.startup() failed; will lazy-init on demand: {e}")

    # Outside the try: whether this service is open to the LAN is worth saying
    # even when session_manager failed to start.
    if SCRAPER_API_KEY:
        logger.info("API key auth ENABLED (%s required on /scrape, /collect, /stream)", _AUTH_HEADER)
    else:
        logger.warning(
            "API key auth DISABLED — SCRAPER_API_KEY is unset, so every host that "
            "can reach :8001 can drive this API and make it fetch any URL. Set it "
            "here and in trading-service to close it."
        )
    yield
    try:
        await session_manager.shutdown()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"session_manager.shutdown() failed: {e}")
    logger.info("scraper-service stopped")


# ── Authentication ───────────────────────────────────────────────────────────
# This service publishes :8001 on 0.0.0.0 of the NAS and will fetch any URL it
# is handed. Until this existed, every host on the LAN could drive the whole API
# with no credential.
#
# Deliberately keyed on the PRESENCE of the secret, not on a boolean flag: a
# static `AUTH_ENABLED=false` pin is a thing someone has to remember to flip,
# and it cannot be armed from the environment during a staged rollout. With this
# shape the sequence is: deploy this (no key set anywhere -> open, exactly as
# today), set the key in trading-service, then set it here — and the live cycle
# never sees a 401 mid-sweep.
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "").strip()
_AUTH_HEADER = "x-scraper-key"


async def require_api_key(x_scraper_key: str = Header(default="")) -> None:
    """Reject a request that does not carry the shared secret.

    No-op while SCRAPER_API_KEY is unset — see above. `/health` never depends on
    this: Docker's healthcheck runs `wget` with no headers, and an auth change
    must not be able to mark the container unhealthy.
    """
    if not SCRAPER_API_KEY:
        return
    # compare_digest, not ==: a plain comparison leaks the key's length and
    # prefix through timing to anyone who can make repeated requests.
    if not hmac.compare_digest(x_scraper_key or "", SCRAPER_API_KEY):
        raise HTTPException(status_code=401, detail=f"missing or invalid {_AUTH_HEADER}")


app = FastAPI(
    title="scraper-service",
    description=(
        "General-purpose scraping microservice. Domain-agnostic. "
        "HTTP / Playwright / crawl4ai engines + Reddit, YouTube, "
        "News/RSS, social and financial-news collectors."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Mount ONLY the scraper routers (root-prefixed): /scrape, /scrape/batch,
# /collect, /stream/{video_id}, /health, /health/engines.
_guard = [Depends(require_api_key)]
app.include_router(scrape.router, tags=["Scraping"], dependencies=_guard)
app.include_router(collect.router, tags=["Collection"], dependencies=_guard)
app.include_router(stream.router, tags=["Streaming"], dependencies=_guard)
# NOT guarded — the container healthcheck is an unauthenticated local wget.
app.include_router(health.router, tags=["Health"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "scraper_main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8001")),
        reload=bool(os.getenv("SCRAPER_RELOAD")),
    )
