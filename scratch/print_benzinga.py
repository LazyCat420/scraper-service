import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.playwright_engine import PlaywrightEngine
from app.core.session_manager import session_manager

async def main():
    await session_manager.startup()
    engine = PlaywrightEngine()
    url = "https://www.benzinga.com/news/24/02/37199999/why-nvidia-shares-are-rising"
    res = await engine.fetch(url, {})
    print(f"Success: {res.success}")
    if res.success:
        print(f"Content Length: {len(res.content)}")
        print("\n--- FULL CONTENT ---")
        print(res.content)
    else:
        print(f"Failed: {res.error}")
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
