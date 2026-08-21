"""tests/test_playwright_engine.py
------------------------------------
Verify that PlaywrightEngine always closes the browser instance,
even when navigation or evaluation throws an exception.
"""

import sys
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.scraper.engines.playwright_engine import PlaywrightEngine


@pytest.mark.asyncio
async def test_playwright_engine_closes_browser_on_exception(monkeypatch):
    engine = PlaywrightEngine()

    mock_browser = AsyncMock()
    mock_browser.close = AsyncMock()

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=RuntimeError("Simulated navigation failure"))
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    class FakeAsyncPlaywright:
        async def __aenter__(self):
            return mock_playwright

        async def __aexit__(self, *args):
            return None

    fake_async_api = MagicMock()
    fake_async_api.async_playwright = lambda: FakeAsyncPlaywright()

    fake_playwright_pkg = MagicMock()
    fake_playwright_pkg.async_api = fake_async_api

    monkeypatch.setitem(sys.modules, "playwright", fake_playwright_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)

    class _NoRate:
        def acquire(self, domain):
            class _Ctx:
                async def __aenter__(self):
                    return None
                async def __aexit__(self, *a):
                    return False
            return _Ctx()

    monkeypatch.setattr("app.scraper.engines.playwright_engine.rate_limiter", _NoRate())

    result = await engine.fetch("https://example.com/failing-page", {})

    assert result.success is False
    assert "Simulated navigation failure" in str(result.error)
    # Ensure browser.close() was called in the finally block
    mock_browser.close.assert_awaited_once()
