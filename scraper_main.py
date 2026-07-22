"""
scraper-service — General-purpose scraping microservice (standalone).

Domain-agnostic. No trading logic, no financial context — all domain knowledge
stays in the calling service. Exposes HTTP, Playwright, crawl4ai and Vision
scraping engines plus the Reddit / YouTube / News / forum collectors.

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

from fastapi import FastAPI

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
    yield
    try:
        await session_manager.shutdown()
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"session_manager.shutdown() failed: {e}")
    logger.info("scraper-service stopped")


app = FastAPI(
    title="scraper-service",
    description=(
        "General-purpose scraping microservice. Domain-agnostic. "
        "HTTP / Playwright / crawl4ai / Vision engines + Reddit, YouTube, "
        "News/RSS and forum (Discourse/XenForo) collectors."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Mount ONLY the scraper routers (root-prefixed): /scrape, /scrape/batch,
# /collect, /stream/{video_id}, /health, /health/engines.
app.include_router(scrape.router, tags=["Scraping"])
app.include_router(collect.router, tags=["Collection"])
app.include_router(stream.router, tags=["Streaming"])
app.include_router(health.router, tags=["Health"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "scraper_main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8001")),
        reload=bool(os.getenv("SCRAPER_RELOAD")),
    )
