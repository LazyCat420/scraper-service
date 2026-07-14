import asyncio
import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.http_engine import HttpEngine
from app.core.session_manager import session_manager


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

async def test_scrape():
    await session_manager.startup()
    engine = HttpEngine()
    
    # Let's test a few sample URLs from typical financial news websites
    test_urls = [
        "https://www.marketwatch.com/story/20-growth-stocks-priced-as-value-stocks-c0f72ad4",
        "https://finance.yahoo.com/news/why-nvidia-stock-dipped-today-153026859.html"
    ]
    
    for url in test_urls:
        print(f"\nScraping URL: {url}")
        res = await engine.fetch(url, {})
        print(f"  Success: {res.success}")
        print(f"  Status Code: {res.status_code}")
        print(f"  Error: {res.error}")
        if res.success and res.content:
            print(f"  Content Length: {len(res.content)} characters")
            print(f"  Snippet: {res.content[:200]}...")
        else:
            print("  No content retrieved.")
            
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(test_scrape())
