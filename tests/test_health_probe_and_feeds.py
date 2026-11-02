"""Tests for /health/search-engines (spaced probe + 20h cache) and
per-feed tracking in failure_cache (2026-09-21)."""
import asyncio

import pytest

import app.scraper.api.routes.health as health_mod
from app.scraper.api.routes.health import feed_health, search_engine_health
from app.scraper.core.failure_cache import FailureCache, SqliteFailureStore


@pytest.fixture(autouse=True)
def _fresh_probe_cache(monkeypatch):
    """Each test starts with a cold probe cache — module state is global."""
    monkeypatch.setattr(health_mod, "_engine_probe_state", None)


def _fake_client(calls, fail_engines=()):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"url": "https://x/1"}] * 3}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append(params.get("engines"))
            if params.get("engines") in fail_engines:
                raise ConnectionError("searxng upstream down")
            return FakeResp()

    return FakeClient


def test_probe_hits_each_engine_with_spacing(monkeypatch):
    calls = []
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(health_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(health_mod.httpx, "AsyncClient", _fake_client(calls))

    r = asyncio.run(search_engine_health())

    assert calls == ["google", "brave", "duckduckgo", "bing", "startpage"]
    # Spacing BETWEEN engines only: 4 sleeps for 5 engines.
    assert sleeps == [health_mod.ENGINE_PROBE_SPACING_S] * 4
    assert r["probed"] is True
    assert r["engines"]["google"] == {"results": 3, "unresponsive_reason": None}
    assert r["cached_at"] is not None
    assert r["next_probe_at"] is not None


def test_cache_prevents_second_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(health_mod.httpx, "AsyncClient", _fake_client(calls))

    first = asyncio.run(search_engine_health())
    assert len(calls) == 5

    second = asyncio.run(search_engine_health())
    assert len(calls) == 5  # no new upstream queries
    assert second["probed"] is False
    assert second["engines"] == first["engines"]
    assert second["cached_at"] == first["cached_at"]


def test_unresponsive_engine_reports_reason(monkeypatch):
    calls = []
    monkeypatch.setattr(
        health_mod.httpx, "AsyncClient", _fake_client(calls, fail_engines={"bing"})
    )

    r = asyncio.run(search_engine_health())

    assert r["engines"]["bing"]["results"] == 0
    assert "searxng upstream down" in r["engines"]["bing"]["unresponsive_reason"]
    # One dead engine must not take the others down with it.
    assert r["engines"]["google"]["unresponsive_reason"] is None


def test_feed_status_tracking(tmp_path):
    store = SqliteFailureStore(str(tmp_path / "failure_cache.db"))
    assert store.enabled

    store.record_feed("https://a.example/rss", False, "HTTP 503", 100.0)
    store.record_feed("https://a.example/rss", False, "HTTP 503", 200.0)
    store.record_feed("https://b.example/rss", True, "", 300.0)

    rows = {r["feed_url"]: r for r in store.feed_statuses()}
    a = rows["https://a.example/rss"]
    assert a["consecutive_failures"] == 2
    assert a["last_error"] == "HTTP 503"
    assert a["last_failure_at"] == 200.0
    assert a["last_success_at"] is None
    # Recovered feed keeps its history but the streak resets.
    b = rows["https://b.example/rss"]
    assert b["consecutive_failures"] == 0
    assert b["last_success_at"] == 300.0
    assert b["last_failure_at"] is None


def test_existing_tables_survive_alongside_feed_status(tmp_path):
    store = SqliteFailureStore(str(tmp_path / "failure_cache.db"))
    store.record("https://x/1", "HTTP 410", 4.0e9)  # expires far in the future
    store.record_quality("example.com", True, 123.0)
    store.record_feed("https://f/rss", False, "0 entries", 5.0)

    assert store.check("https://x/1") == ("HTTP 410", 4.0e9)
    assert store.quality_of("example.com") == (0, 1, 0.0)
    assert store.feed_statuses()[0]["last_error"] == "0 entries"


def test_feed_health_route_reads_store(monkeypatch, tmp_path):
    store = SqliteFailureStore(str(tmp_path / "failure_cache.db"))
    store.record_feed("https://f/rss", False, "HTTP 503", 100.0)
    monkeypatch.setattr(health_mod, "failure_cache", FailureCache(store=store))

    r = asyncio.run(feed_health())

    assert r["count"] == 1
    assert r["store_enabled"] is True
    feed = r["feeds"][0]
    assert feed["feed_url"] == "https://f/rss"
    assert feed["last_success_at"] is None
    assert feed["last_failure_at"].startswith("1970-01-01T00:01:40")


def test_feed_health_route_empty_when_store_disabled(monkeypatch):
    monkeypatch.setattr(health_mod, "failure_cache", FailureCache(store=None))

    r = asyncio.run(feed_health())

    assert r["count"] == 0
    assert r["store_enabled"] is False
