"""Offline unit tests — no network access required.

Run with: pytest -m "not live" to execute only these.
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.reddit_purge_collector import RedditPurgeCollector
from app.core.rate_limiter import RateLimiter


class TestExtractTickers:
    def setup_method(self):
        self.collector = RedditPurgeCollector()

    def test_extracts_dollar_prefixed_tickers(self):
        tickers = self.collector.extract_tickers("Buying $AMD and $NVDA today")
        assert set(tickers) == {"AMD", "NVDA"}

    def test_extracts_bare_uppercase_tickers(self):
        tickers = self.collector.extract_tickers("TSLA to the moon")
        assert "TSLA" in tickers

    def test_ignores_lowercase_and_short_words(self):
        assert self.collector.extract_tickers("buy the dip now") == []
        # Single letters never match the 2-5 char pattern
        assert self.collector.extract_tickers("I A") == []

    def test_ignores_long_uppercase_words(self):
        # 6+ uppercase chars are not valid tickers
        assert "BUYING" not in self.collector.extract_tickers("BUYING stocks")

    def test_deduplicates(self):
        tickers = self.collector.extract_tickers("$GME GME $GME")
        assert tickers == ["GME"]

    def test_empty_input(self):
        assert self.collector.extract_tickers("") == []
        assert self.collector.extract_tickers(None) == []


class TestRateLimiter:
    async def test_enforces_min_interval_per_domain(self):
        limiter = RateLimiter()
        # reddit.com is limited to 0.5 req/s → 2s min interval, too slow for a
        # unit test; use an unknown domain (DEFAULT_RATE = 1 req/s → 1s interval)
        start = time.monotonic()
        async with limiter.acquire("example-test.invalid"):
            pass
        async with limiter.acquire("example-test.invalid"):
            pass
        elapsed = time.monotonic() - start
        assert elapsed >= 0.9, f"second request should have waited ~1s, elapsed={elapsed:.2f}"

    async def test_domains_do_not_block_each_other(self):
        limiter = RateLimiter()

        async def hit(domain):
            async with limiter.acquire(domain):
                return time.monotonic()

        start = time.monotonic()
        await asyncio.gather(hit("a.invalid"), hit("b.invalid"), hit("c.invalid"))
        elapsed = time.monotonic() - start
        # First hit to each domain never sleeps, so this should be near-instant
        assert elapsed < 0.5, f"independent domains must not serialize, elapsed={elapsed:.2f}"
