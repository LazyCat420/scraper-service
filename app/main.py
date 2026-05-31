"""
scraper-service — General-purpose scraping microservice.

Domain-agnostic. No trading logic, no financial context.
All domain knowledge stays in the calling service.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import collect, health, scrape, stream
from app.core.session_manager import session_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle for the scraper service."""
    await session_manager.startup()
    logger.info("scraper-service started")
    yield
    await session_manager.shutdown()
    logger.info("scraper-service stopped")


app = FastAPI(
    title="scraper-service",
    description=(
        "General-purpose scraping microservice. Domain-agnostic. "
        "Provides HTTP, Playwright, crawl4ai, and Vision scraping engines, "
        "plus Reddit, YouTube, and News/RSS collectors."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(scrape.router, tags=["Scraping"])
app.include_router(collect.router, tags=["Collection"])
app.include_router(stream.router, tags=["Streaming"])
app.include_router(health.router, tags=["Health"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8001")),
        reload=True,
    )
