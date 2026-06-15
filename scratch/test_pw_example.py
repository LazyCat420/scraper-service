import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.playwright_engine import PlaywrightEngine
from app.core.session_manager import session_manager

url = "https://example.com"

async def main():
    await session_manager.startup()
    engine = PlaywrightEngine()
    
    print(f"Fetching URL: {url}")
    res = await engine.fetch(url, {})
    
    print(f"Success: {res.success}")
    print(f"Status: {getattr(res, 'status_code', 'N/A')}")
    print(f"Error: {res.error}")
    if res.content:
        print(f"Content Length: {len(res.content)}")
        print(f"Snippet: {res.content[:300].strip()}...")
        
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
