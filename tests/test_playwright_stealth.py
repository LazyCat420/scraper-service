import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test_stealth():
    url = "https://www.marketwatch.com/story/20-growth-stocks-priced-as-value-stocks-c0f72ad4"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Apply async stealth
        try:
            await Stealth().apply_stealth_async(page)
            print("Successfully applied stealth!")
        except Exception as e:
            print(f"Failed to apply stealth: {e}")
            
        try:
            print(f"Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("Navigated successfully!")
            content = await page.evaluate("() => document.body.innerText")
            print(f"Content length: {len(content)} characters")
            print(f"Snippet: {content[:300]}...")
        except Exception as e:
            print(f"Navigation failed: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_stealth())
