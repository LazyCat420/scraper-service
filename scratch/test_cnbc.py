import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.http_engine import HttpEngine
from app.engines.playwright_engine import PlaywrightEngine
from app.core.session_manager import session_manager

url = "https://www.cnbc.com/2026/06/15/anthropic-mythos-trump-ai.html"

async def main():
    await session_manager.startup()
    
    http_eng = HttpEngine()
    pw_eng = PlaywrightEngine()
    
    print(f"Testing CNBC URL: {url}\n")
    
    # 1. HTTP Engine
    print("--- [HTTP Engine] ---")
    res_http = await http_eng.fetch(url, {})
    print(f"Success: {res_http.success} (Status: {res_http.status_code})")
    if res_http.success and res_http.content:
        print(f"Content Length: {len(res_http.content)} characters")
        print(f"Snippet: {res_http.content[:400]}...")
    else:
        print(f"Failed: {res_http.error}")
        
    # 2. Playwright Engine
    print("\n--- [Playwright Engine] ---")
    res_pw = await pw_eng.fetch(url, {})
    print(f"Success: {res_pw.success}")
    if res_pw.success and res_pw.content:
        print(f"Content Length: {len(res_pw.content)} characters")
        print(f"Snippet: {res_pw.content[:400]}...")
    else:
        print(f"Failed: {res_pw.error}")
        
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
