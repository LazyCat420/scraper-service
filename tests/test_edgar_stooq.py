"""Tests for EDGAR and Stooq collectors (2026-09-21)."""
import asyncio

import httpx
import pytest


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)
    def json(self):
        return self._payload
    @property
    def text(self):
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self._responses = responses
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def get(self, url, params=None):
        for pattern, resp in self._responses:
            if pattern in url:
                return resp
        raise AssertionError(f"unexpected url {url}")


def test_edgar_resolves_cik_and_maps_filings(monkeypatch):
    import app.scraper.collectors.edgar_collector as mod
    mod._cik_cache.clear()
    tickers = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    submissions = {"name": "Apple Inc.", "filings": {"recent": {
        "form": ["10-K", "8-K"],
        "filingDate": ["2026-09-01", "2026-09-05"],
        "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
        "primaryDocument": ["a.htm", "b.htm"],
        "reportDate": ["2026-08-31", "2026-09-04"],
        "primaryDocDescription": ["", ""],
    }}}
    fake = FakeClient([("company_tickers", FakeResp(tickers)),
                       ("submissions", FakeResp(submissions))])
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)

    r = asyncio.run(mod.EdgarCollector().recent_filings("AAPL", limit=5))
    assert len(r) == 2
    assert r[0]["form"] == "10-K"
    assert "edgar/data/320193/000032019326000001" in r[0]["url"]


def test_edgar_unknown_ticker_raises(monkeypatch):
    import app.scraper.collectors.edgar_collector as mod
    mod._cik_cache.clear()
    fake = FakeClient([("company_tickers", FakeResp({"0": {"cik_str": 1, "ticker": "ZZZ"}}))])
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)
    with pytest.raises(LookupError):
        asyncio.run(mod.EdgarCollector().recent_filings("AAPL"))


def test_edgar_form_filter(monkeypatch):
    import app.scraper.collectors.edgar_collector as mod
    mod._cik_cache.clear()
    submissions = {"name": "Apple Inc.", "filings": {"recent": {
        "form": ["10-K", "8-K", "4"],
        "filingDate": ["2026-09-01", "2026-09-05", "2026-09-06"],
        "accessionNumber": ["a1", "a2", "a3"],
        "primaryDocument": ["a.htm", "b.htm", "c.htm"],
    }}}
    fake = FakeClient([("company_tickers", FakeResp({"0": {"cik_str": 1, "ticker": "AAPL"}})),
                       ("submissions", FakeResp(submissions))])
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)
    r = asyncio.run(mod.EdgarCollector().recent_filings("AAPL", forms=["8-K"]))
    assert [x["form"] for x in r] == ["8-K"]


def test_stooq_parses_history_csv(monkeypatch):
    import app.scraper.collectors.stooq_collector as mod
    csv = ("Date,Open,High,Low,Close,Volume\n"
           "2026-09-01,100,101,99,100.5,12345\n"
           "2026-09-02,100.5,102,100,101.75,23456\n")
    fake = FakeClient([("q/d/l", FakeResp(csv))])
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)

    r = asyncio.run(mod.StooqCollector().history("aapl", "20260901", "20260919"))
    assert len(r) == 2
    assert r[1]["close"] == "101.75"
    assert r[0]["displayUrl"] == "stooq.com"


def test_stooq_no_data_is_empty_not_error(monkeypatch):
    import app.scraper.collectors.stooq_collector as mod
    fake = FakeClient([("q/d/l", FakeResp("No data"))])
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)
    assert asyncio.run(mod.StooqCollector().history("aapl", "20260901", "20260902")) == []


def test_stooq_challenge_payload_raises_honestly(monkeypatch):
    """A JS bot-wall page must raise, never parse as rows."""
    import app.scraper.collectors.stooq_collector as mod
    fake = FakeClient([("q/d/l", FakeResp("<!DOCTYPE html><noscript>verify</noscript>"))])
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **k: fake)
    with pytest.raises(ValueError):
        asyncio.run(mod.StooqCollector().history("aapl", "20260901", "20260902"))
