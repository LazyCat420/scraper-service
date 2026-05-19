"""
xenforo_collector.py — XenForo forum collector
-------------------------------------------------
Scrapes posts from XenForo-based forums via HTML parsing.
XenForo forums (Rollitup, THCFarmer) don't have public APIs,
so we parse the HTML structure.

Some XenForo sites may require Playwright (Cloudflare protected).
This collector tries HTTP first, falls back to Playwright.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.rate_limiter import rate_limiter
from app.core.session_manager import session_manager

logger = logging.getLogger(__name__)


@dataclass
class XenForoPost:
    """Normalized XenForo forum post data."""
    id: str
    thread_id: str
    title: str
    body: str
    author: str
    created_at: datetime | None
    url: str
    forum_name: str
    subforum: str
    post_number: int = 1
    reaction_score: int = 0


class XenForoCollector:
    """Scrapes posts from XenForo-based forums.

    XenForo HTML structure (v2.x):
      - Forum list: .node-title a
      - Thread list: .structItem-title a
      - Thread metadata: .structItem-minor time[datetime]
      - Post body: article.message-body .bbWrapper
      - Post author: .message-name a
      - Post date: time.u-dt[datetime]

    Works with: rollitup.org, thcfarmer.com, and other XenForo 2.x sites.
    """

    def __init__(self, base_url: str, forum_name: str = "xenforo"):
        self.base_url = base_url.rstrip("/")
        self.forum_name = forum_name
        self._use_playwright = False

    async def get_forum_threads(
        self,
        subforum_path: str,
        limit: int = 30,
        page: int = 1,
    ) -> list[XenForoPost]:
        """Get thread listings from a subforum.

        Args:
            subforum_path: e.g. 'f/grow-journals.54/' or 'f/breeders-paradise.94/'
            limit: Max threads to return
            page: Page number (1-indexed)
        """
        url = f"{self.base_url}/{subforum_path}"
        if page > 1:
            url += f"page-{page}"

        html = await self._fetch_html(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        threads = []

        # XenForo thread list items
        for item in soup.select(".structItem"):
            title_el = item.select_one(".structItem-title a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            thread_url = title_el.get("href", "")
            if thread_url:
                thread_url = urljoin(self.base_url, thread_url)

            # Extract thread ID from URL
            thread_id = ""
            id_match = re.search(r'\.(\d+)/?$', thread_url)
            if id_match:
                thread_id = id_match.group(1)

            # Author
            author_el = item.select_one(".structItem-minor .username")
            author = author_el.get_text(strip=True) if author_el else ""

            # Date
            time_el = item.select_one("time[datetime]")
            created_at = None
            if time_el:
                try:
                    created_at = datetime.fromisoformat(
                        time_el["datetime"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            # Reply count
            reply_el = item.select_one(".structItem-cell--meta dd")
            reaction_score = 0
            if reply_el:
                try:
                    reaction_score = int(reply_el.get_text(strip=True).replace(",", ""))
                except ValueError:
                    pass

            # Snippet/preview
            snippet_el = item.select_one(".structItem-snippet")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            threads.append(XenForoPost(
                id=thread_id or hashlib.md5(title.encode()).hexdigest()[:12],
                thread_id=thread_id,
                title=title,
                body=snippet,
                author=author,
                created_at=created_at,
                url=thread_url,
                forum_name=self.forum_name,
                subforum=subforum_path,
                reaction_score=reaction_score,
            ))

            if len(threads) >= limit:
                break

        logger.info(f"[xenforo] {self.forum_name}/{subforum_path}: {len(threads)} threads")
        return threads

    async def get_thread_posts(
        self,
        thread_url: str,
        max_posts: int = 50,
        max_pages: int = 3,
    ) -> list[XenForoPost]:
        """Get all posts from a specific thread.

        Paginates through thread pages to collect posts.
        """
        all_posts: list[XenForoPost] = []
        thread_id = ""
        id_match = re.search(r'\.(\d+)/?$', thread_url.split("/page-")[0])
        if id_match:
            thread_id = id_match.group(1)

        for page in range(1, max_pages + 1):
            page_url = thread_url
            if page > 1:
                page_url = f"{thread_url.rstrip('/')}/page-{page}"

            html = await self._fetch_html(page_url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")

            # Get thread title
            title_el = soup.select_one("h1.p-title-value")
            title = title_el.get_text(strip=True) if title_el else ""

            # Parse posts
            post_elements = soup.select("article.message")
            if not post_elements:
                break

            for post_el in post_elements:
                # Post body
                body_el = post_el.select_one(".message-body .bbWrapper")
                if not body_el:
                    continue
                body = body_el.get_text(separator=" ", strip=True)
                if not body or len(body) < 10:
                    continue

                # Post ID
                post_id = post_el.get("data-content", "").replace("post-", "")

                # Author
                author_el = post_el.select_one(".message-name a, .message-name span")
                author = author_el.get_text(strip=True) if author_el else ""

                # Date
                time_el = post_el.select_one("time.u-dt[datetime]")
                created_at = None
                if time_el:
                    try:
                        created_at = datetime.fromisoformat(
                            time_el["datetime"].replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

                # Post number
                post_num_el = post_el.select_one(".message-attribution-opposite a")
                post_number = 1
                if post_num_el:
                    try:
                        post_number = int(post_num_el.get_text(strip=True).lstrip("#"))
                    except ValueError:
                        pass

                # Reaction score
                reaction_el = post_el.select_one(".reactionsBar")
                reaction_score = 0
                if reaction_el:
                    score_text = reaction_el.get_text(strip=True)
                    nums = re.findall(r'\d+', score_text)
                    if nums:
                        reaction_score = int(nums[0])

                all_posts.append(XenForoPost(
                    id=post_id or hashlib.md5(body[:100].encode()).hexdigest()[:12],
                    thread_id=thread_id,
                    title=title,
                    body=body[:5000],  # Cap body length
                    author=author,
                    created_at=created_at,
                    url=f"{self.base_url}/posts/{post_id}/" if post_id else page_url,
                    forum_name=self.forum_name,
                    subforum="",
                    post_number=post_number,
                    reaction_score=reaction_score,
                ))

                if len(all_posts) >= max_posts:
                    break

            if len(all_posts) >= max_posts:
                break

            # Rate limit between pages
            await asyncio.sleep(2.0)

        logger.info(f"[xenforo] Thread {thread_id}: {len(all_posts)} posts")
        return all_posts

    async def search(
        self,
        query: str,
        limit: int = 50,
    ) -> list[XenForoPost]:
        """Search the forum using XenForo's search endpoint."""
        url = f"{self.base_url}/search/search"
        params = {"keywords": query, "type": "post", "order": "relevance"}

        html = await self._fetch_html(url, params=params)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        for item in soup.select(".block-row"):
            title_el = item.select_one("h3 a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            result_url = urljoin(self.base_url, title_el.get("href", ""))

            snippet_el = item.select_one(".contentRow-snippet")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            author_el = item.select_one(".contentRow-minor a.username")
            author = author_el.get_text(strip=True) if author_el else ""

            time_el = item.select_one("time[datetime]")
            created_at = None
            if time_el:
                try:
                    created_at = datetime.fromisoformat(
                        time_el["datetime"].replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            results.append(XenForoPost(
                id=hashlib.md5(result_url.encode()).hexdigest()[:12],
                thread_id="",
                title=title,
                body=snippet,
                author=author,
                created_at=created_at,
                url=result_url,
                forum_name=self.forum_name,
                subforum="search",
            ))

            if len(results) >= limit:
                break

        logger.info(f"[xenforo] Search '{query}': {len(results)} results")
        return results

    async def _fetch_html(self, url: str, params: dict | None = None) -> str | None:
        """Fetch page HTML — tries HTTP first, falls back to Playwright."""
        domain = urlparse(self.base_url).netloc

        # Try plain HTTP first
        if not self._use_playwright:
            try:
                async with rate_limiter.acquire(domain):
                    r = await session_manager.client.get(url, params=params, timeout=30.0)

                if r.status_code == 200 and len(r.text) > 1000:
                    return r.text

                if r.status_code == 403:
                    logger.info(f"[xenforo] {self.forum_name}: 403 — switching to Playwright")
                    self._use_playwright = True

            except Exception as e:
                logger.warning(f"[xenforo] HTTP failed for {url}: {e}")
                self._use_playwright = True

        # Playwright fallback
        if self._use_playwright:
            try:
                from app.engines.playwright_engine import PlaywrightEngine
                engine = PlaywrightEngine()
                result = await engine.fetch(url, {"wait_for": ".structItem, article.message"})
                if result.success and result.content:
                    # We need raw HTML, not extracted text
                    # Re-fetch with raw HTML option
                    from playwright.async_api import async_playwright
                    import random

                    async with rate_limiter.acquire(domain):
                        async with async_playwright() as p:
                            browser = await p.chromium.launch(
                                headless=True,
                                args=["--disable-blink-features=AutomationControlled"],
                            )
                            context = await browser.new_context(
                                viewport={"width": 1280, "height": 900 + random.randint(0, 50)},
                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            )
                            page = await context.new_page()
                            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                            await page.wait_for_timeout(2000)
                            html = await page.content()
                            await browser.close()
                            return html
            except Exception as e:
                logger.error(f"[xenforo] Playwright fallback failed: {e}")

        return None


def _serialize_xenforo_post(post: XenForoPost) -> dict:
    """Convert XenForoPost to JSON-safe dict for API responses."""
    return {
        "id": post.id,
        "thread_id": post.thread_id,
        "title": post.title,
        "body": post.body,
        "author": post.author,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "url": post.url,
        "forum_name": post.forum_name,
        "subforum": post.subforum,
        "post_number": post.post_number,
        "reaction_score": post.reaction_score,
    }
