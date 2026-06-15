import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.auto_engine import AutoEngine
from app.core.session_manager import session_manager

url = "https://www.marketwatch.com/story/im-spending-170-000-to-upgrade-my-home-for-my-aging-parents-can-i-get-tax-breaks-3adf0236"

async def main():
    await session_manager.startup()
    engine = AutoEngine()
    
    print(f"Testing URL for fallback: {url}\n")
    res = await engine.fetch(url, {})
    
    print(f"Success: {res.success}")
    print(f"Engine Used: {res.engine_used}")
    print(f"Status Code: {res.status_code}")
    print(f"Error: {res.error}")
    if res.content:
        print(f"Content Length: {len(res.content)} characters")
        print(f"Snippet: {res.content[:300].strip()}...")
        
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
