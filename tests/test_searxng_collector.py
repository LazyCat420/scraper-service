"""Tests for the SearXNG collector (2026-09-21)."""
import asyncio
import os

import pytest

from app.scraper.collectors.searxng_collector import SearxngCollector, searxng_disabled


def test_disabled_flag_short_circuits(monkeypatch):
    monkeypatch.setenv("DISABLE_SEARXNG_SEARCH", "true")
    assert searxng_disabled() is True
    r = asyncio.run(SearxngCollector().search("anything"))
    assert r == []


def test_item_shape_and_display_url(monkeypatch):
    """parsed_url is [scheme, hostname, path, ...]; displayUrl must be hostname."""

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [{
                "title": "Example", "url": "https://www.example.com/page",
                "content": "snippet text",
                "parsed_url": ["https", "www.example.com", "/page", "", "", None],
                "engine": "google",
                "publishedDate": None,
            }]}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None): return FakeResp()

    import app.scraper.collectors.searxng_collector as mod
    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)

    r = asyncio.run(SearxngCollector().search("q", limit=5))
    assert len(r) == 1
    item = r[0]
    assert item["title"] == "Example"
    assert item["url"] == "https://www.example.com/page"
    assert item["displayUrl"] == "www.example.com"   # not the path
    assert item["engine"] == "google"


def test_outage_raises_not_quiet(monkeypatch):
    """Transport failure must raise so /collect sets success=False (F2 lesson)."""

    class BrokenClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None): raise ConnectionError("searxng down")

    import app.scraper.collectors.searxng_collector as mod
    monkeypatch.setattr(mod.httpx, "AsyncClient", BrokenClient)

    with pytest.raises(ConnectionError):
        asyncio.run(SearxngCollector().search("q"))
