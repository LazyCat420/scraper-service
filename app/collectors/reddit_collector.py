"""
reddit_collector.py — Domain-agnostic Reddit post collection
--------------------------------------------------------------
Ported from trading-service's reddit_collector.py.
All trading-specific logic (ticker extraction, financial subreddits,
DB writes) has been REMOVED. This collector knows HOW to pull
Reddit posts — the caller decides WHICH subreddits and keywords.

Uses Reddit's public .json API — no API key needed for basic collection.
For higher volume, configure REDDIT_CLIENT_ID/SECRET for asyncpraw.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.core.rate_limiter import rate_limiter
from app.core.session_manager import session_manager

logger = logging.getLogger(__name__)


@dataclass
class RedditPost:
    """Normalized Reddit post data."""
    id: str
    title: str
    body: str
    score: int
    url: str
    subreddit: str
    created_at: datetime
    author: str
    num_comments: int
    flair: str | None = None
    upvote_ratio: float = 0.0
    awards: int = 0
    permalink: str = ""


def _is_quality_post(post: dict, min_score: int = 3, min_comments: int = 2) -> bool:
    """Fast deterministic filter — no LLM needed.
    Ported from trading-service. Filters removed/deleted, NSFW, low-effort.
    """
    body = post.get("selftext", "")
    if body in ("[removed]", "[deleted]"):
        return False
    if post.get("over_18"):
        return False
    if post.get("score", 0) < min_score:
        return False
    if post.get("num_comments", 0) < min_comments:
        return False
    if len(body) < 50 and post.get("score", 0) < 50:
        return False
    return True


def _post_to_dataclass(post: dict, subreddit: str) -> RedditPost:
    """Convert raw Reddit API post dict to RedditPost dataclass."""
    created_utc = post.get("created_utc", 0)
    return RedditPost(
        id=post.get("id", hashlib.md5(post.get("title", "").encode()).hexdigest()[:12]),
        title=post.get("title", ""),
        body=post.get("selftext", ""),
        score=post.get("score", 0),
        url=post.get("url", ""),
        subreddit=post.get("subreddit", subreddit),
        created_at=datetime.utcfromtimestamp(created_utc) if created_utc else datetime.utcnow(),
        author=post.get("author", ""),
        num_comments=post.get("num_comments", 0),
        flair=post.get("link_flair_text"),
        upvote_ratio=post.get("upvote_ratio", 0.0),
        awards=post.get("total_awards_received", 0),
        permalink=post.get("permalink", ""),
    )


class RedditCollector:
    """Collects Reddit posts from specified subreddits.

    Two modes:
      1. get_posts() — Top/hot posts from subreddits (general sweep)
      2. search() — Full-text search within subreddits

    All filtering context (subreddits, keywords) comes from the CALLER.
    This class has zero domain knowledge.
    """

    async def get_posts(
        self,
        subreddits: list[str],
        limit: int = 100,
        keywords: list[str] | None = None,
        sort: str = "hot",
        time_filter: str = "day",
    ) -> list[RedditPost]:
        """Collect posts from subreddits.

        Args:
            subreddits: List of subreddit names (without r/)
            limit: Max posts per subreddit
            keywords: Optional keyword filter (post must contain at least one)
            sort: One of 'hot', 'top', 'new', 'rising'
            time_filter: Time window for 'top' sort — 'hour', 'day', 'week', 'month', 'year', 'all'
        """
        all_posts: list[RedditPost] = []

        for sub in subreddits:
            try:
                posts = await self._fetch_subreddit(sub, sort, time_filter, limit)
                for post_data in posts:
                    if not _is_quality_post(post_data):
                        continue

                    # Keyword filter
                    if keywords:
                        full_text = f"{post_data.get('title', '')} {post_data.get('selftext', '')}".lower()
                        if not any(kw.lower() in full_text for kw in keywords):
                            continue

                    all_posts.append(_post_to_dataclass(post_data, sub))

                # Rate limit between subreddits
                await asyncio.sleep(2.0)

            except Exception as e:
                logger.error(f"[reddit] r/{sub} error: {e}")

        logger.info(f"[reddit] Collected {len(all_posts)} posts from {len(subreddits)} subreddits")
        return all_posts

    async def search(
        self,
        query: str,
        subreddits: list[str],
        limit: int = 50,
        time_filter: str = "week",
    ) -> list[RedditPost]:
        """Full-text search within subreddits.

        Uses Reddit's search API with restrict_sr to stay within specified subs.
        """
        all_posts: list[RedditPost] = []
        seen_ids: set[str] = set()

        # Build multi-subreddit string for combined search
        multi_sub = "+".join(subreddits)

        try:
            domain = "www.reddit.com"
            url = f"https://www.reddit.com/r/{multi_sub}/search.json"
            params = {
                "q": query,
                "restrict_sr": "on",
                "sort": "relevance",
                "t": time_filter,
                "limit": limit,
                "type": "link",
            }

            async with rate_limiter.acquire(domain):
                r = await session_manager.client.get(url, params=params, timeout=30.0)

            if r.status_code != 200:
                logger.warning(f"[reddit] Search HTTP {r.status_code}")
                return all_posts

            data = r.json()
            posts = data.get("data", {}).get("children", [])

            for post_wrapper in posts:
                post = post_wrapper.get("data", {})
                if not post:
                    continue

                post_id = post.get("id", "")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                if not _is_quality_post(post):
                    continue

                all_posts.append(_post_to_dataclass(post, post.get("subreddit", multi_sub)))

        except Exception as e:
            logger.error(f"[reddit] Search error: {e}")

        logger.info(f"[reddit] Search '{query}': {len(all_posts)} results")
        return all_posts

    async def _fetch_subreddit(
        self, subreddit: str, sort: str, time_filter: str, limit: int
    ) -> list[dict]:
        """Fetch posts from a single subreddit using public JSON API."""
        domain = "www.reddit.com"
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
        params = {"t": time_filter, "limit": limit}

        async with rate_limiter.acquire(domain):
            r = await session_manager.client.get(url, params=params, timeout=30.0)

        if r.status_code == 429:
            logger.warning(f"[reddit] r/{subreddit}: rate limited")
            return []

        if r.status_code != 200:
            logger.warning(f"[reddit] r/{subreddit}: HTTP {r.status_code}")
            return []

        data = r.json()
        children = data.get("data", {}).get("children", [])
        return [c.get("data", {}) for c in children if c.get("data")]


def _serialize_post(post: RedditPost) -> dict:
    """Convert RedditPost to JSON-safe dict for API responses."""
    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "score": post.score,
        "url": post.url,
        "subreddit": post.subreddit,
        "created_at": post.created_at.isoformat(),
        "author": post.author,
        "num_comments": post.num_comments,
        "flair": post.flair,
        "upvote_ratio": post.upvote_ratio,
        "awards": post.awards,
        "permalink": f"https://reddit.com{post.permalink}" if post.permalink else "",
    }
