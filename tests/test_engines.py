import asyncio
import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.http_engine import HttpEngine
from app.engines.playwright_engine import PlaywrightEngine
from app.engines.crawl4ai_engine import Crawl4aiEngine
from app.engines.auto_engine import AutoEngine
from app.core.session_manager import session_manager


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

async def test_engines():
    await session_manager.startup()
    
    url = "https://www.cnbc.com/2026/06/15/anthropic-mythos-trump-ai.html"
    
    engines = {
        "http": HttpEngine(),
        "playwright": PlaywrightEngine(),
        "crawl4ai": Crawl4aiEngine(),
        "auto": AutoEngine()
    }
    
    for name, engine in engines.items():
        print(f"\n--- Testing Engine: {name} ---")
        try:
            res = await engine.fetch(url, {})
            print(f"Success: {res.success}")
            print(f"Status Code: {getattr(res, 'status_code', 'N/A')}")
            print(f"Error: {res.error}")
            if res.success and res.content:
                print(f"Content Length: {len(res.content)} characters")
                print(f"Snippet: {res.content[:300]}...")
            else:
                print("No content retrieved.")
        except Exception as e:
            print(f"Engine {name} failed with exception: {e}")
            
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(test_engines())
