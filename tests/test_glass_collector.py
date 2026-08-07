"""
test_glass_collector.py
-------------------------
Unit tests for GlassCollector in scraper-service.
"""

import pytest
from app.scraper.collectors.glass_collector import GlassCollector

@pytest.mark.asyncio
async def test_glass_collector_state_extraction():
    collector = GlassCollector()
    text = "Banjo Glass is an iconic heady artist based out of California creating biomechanical functional art."
    state = collector._extract_state_code(text)
    assert state == "CA"

@pytest.mark.asyncio
async def test_glass_collector_collab_extraction():
    collector = GlassCollector()
    text = "Check out the legendary piece: Banjo x Elbo Collaboration on full display!"
    collabs = collector._extract_collaborations(text, [])
    assert len(collabs) > 0
    assert collabs[0]["artist_1_name"] == "Banjo"
    assert collabs[0]["artist_2_name"] == "Elbo"

@pytest.mark.asyncio
async def test_glass_collector_mock_html(monkeypatch):
    collector = GlassCollector()
    
    mock_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sovereignty Glass - Benchmark Scientific Glass</title>
        <meta name="description" content="Handcrafted functional glass in California. Featuring collabs with Bob Snodgrass and Salt Glass." />
    </head>
    <body>
        <h1>Sovereignty Glass Studio</h1>
        <p>Located in CA. Check out our featured artists: <a href="https://instagram.com/saltglass">Salt Glass</a> and <a href="https://snodgrassglass.com">Bob Snodgrass</a>.</p>
    </body>
    </html>
    """

    async def mock_fetch(url):
        return mock_html

    monkeypatch.setattr(collector, "_fetch_html", mock_fetch)

    res = await collector.collect("https://sovereigntyglass.com")
    assert res["success"] is True
    assert res["state_code"] == "CA"
    assert len(res["discovered_artists"]) >= 2
