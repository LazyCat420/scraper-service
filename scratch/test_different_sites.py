import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.http_engine import HttpEngine
from app.engines.playwright_engine import PlaywrightEngine
from app.core.session_manager import session_manager

test_urls = [
    # Yahoo Finance article
    "https://finance.yahoo.com/news/why-nvidia-stock-dipped-today-153026859.html",
    # Benzinga article
    "https://www.benzinga.com/news/24/02/37199999/why-nvidia-shares-are-rising",
    # Seeking Alpha article
    "https://seekingalpha.com/news/4060000-nvidia-shares-rise-as-analysts-hike-targets-after-earnings",
    # Reuters
    "https://www.reuters.com/technology/nvidia-forecasts-first-quarter-revenue-above-estimates-2024-02-21/"
]

async def test():
    await session_manager.startup()
    
    http_eng = HttpEngine()
    pw_eng = PlaywrightEngine()
    
    for url in test_urls:
        print(f"\n==================================================")
        print(f"URL: {url}")
        
        # Test HTTP
        print("\n--- [HTTP Engine] ---")
        try:
            res = await http_eng.fetch(url, {})
            print(f"Success: {res.success} (Status: {res.status_code})")
            if res.success and res.content:
                print(f"Content Length: {len(res.content)} characters")
                print(f"Snippet: {res.content[:300].strip()}...")
            else:
                print(f"No content or failed: {res.error}")
        except Exception as e:
            print(f"HTTP failed: {e}")
            
        # Test Playwright
        print("\n--- [Playwright Engine] ---")
        try:
            res = await pw_eng.fetch(url, {})
            print(f"Success: {res.success}")
            if res.success and res.content:
                print(f"Content Length: {len(res.content)} characters")
                print(f"Snippet: {res.content[:300].strip()}...")
            else:
                print(f"No content or failed: {res.error}")
        except Exception as e:
            print(f"Playwright failed: {e}")
            
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(test())
