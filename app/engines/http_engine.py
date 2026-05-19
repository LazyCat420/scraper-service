"""
http_engine.py — Primary scraping engine
-----------------------------------------
Plain HTTPX requests + BeautifulSoup extraction.
Good for: server-rendered HTML, JSON APIs, RSS feeds.

Ported from trading-service SmartClient + news_collector patterns.
Strips all trading-specific logic — this is pure HTTP fetching.
"""

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.core.base_engine import BaseEngine
from app.core.base_result import ScrapeResult
from app.core.rate_limiter import rate_limiter
from app.core.session_manager import session_manager

logger = logging.getLogger(__name__)


def _extract_text_from_html(html: str, max_chars: int = 15000) -> str:
    """Extract readable text from HTML using trafilatura (ported from news_collector).

    Falls back to BeautifulSoup if trafilatura is not installed or fails.
    """
    # Try trafilatura first (best article extraction)
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            include_links=False,
            include_images=False,
            include_tables=False,
            no_fallback=False,
        )
        if text and len(text) > 50:
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else ""
    except Exception:
        return ""


class HttpEngine(BaseEngine):
    """Plain HTTP scraping engine using shared session manager.

    Supports:
    - Raw HTML fetching
    - CSS selector extraction via BeautifulSoup
    - JSON API responses (auto-detected from Content-Type)
    - Article text extraction via trafilatura
    - Per-domain rate limiting
    """

    async def fetch(self, url: str, options: dict[str, Any]) -> ScrapeResult:
        domain = urlparse(url).netloc
        try:
            async with rate_limiter.acquire(domain):
                response = await session_manager.client.get(url)

            content_type = response.headers.get("content-type", "")

            # JSON responses — return data directly
            if "application/json" in content_type:
                try:
                    json_data = response.json()
                    return ScrapeResult(
                        url=url,
                        success=True,
                        content=response.text,
                        data=json_data if isinstance(json_data, dict) else {"items": json_data},
                        error=None,
                        engine_used="http",
                        scraped_at=datetime.utcnow(),
                        status_code=response.status_code,
                    )
                except Exception:
                    pass

            # HTML responses — parse and extract
            html = response.text
            data: dict[str, Any] = {}

            # Apply CSS selector extraction if requested
            extract_map = options.get("extract")
            if extract_map and isinstance(extract_map, dict):
                soup = BeautifulSoup(html, "lxml")
                for field_name, selector in extract_map.items():
                    elements = soup.select(selector)
                    data[field_name] = [el.get_text(strip=True) for el in elements]

            # Extract article text
            extracted_text = _extract_text_from_html(html)

            return ScrapeResult(
                url=url,
                success=True,
                content=extracted_text or html[:15000],
                data=data,
                error=None,
                engine_used="http",
                scraped_at=datetime.utcnow(),
                status_code=response.status_code,
            )

        except Exception as e:
            logger.error(f"[http] Error fetching {url}: {e}")
            return ScrapeResult(
                url=url,
                success=False,
                content=None,
                data={},
                error=str(e),
                engine_used="http",
                scraped_at=datetime.utcnow(),
            )

    async def health_check(self) -> bool:
        try:
            r = await session_manager.client.get(
                "https://httpbin.org/get", timeout=5
            )
            return r.status_code == 200
        except Exception:
            return False
