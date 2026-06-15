import asyncio
import os
import sys
import base64

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engines.playwright_engine import PlaywrightEngine
from app.core.session_manager import session_manager

async def main():
    await session_manager.startup()
    engine = PlaywrightEngine()
    
    # Test Benzinga
    url = "https://www.benzinga.com/news/24/02/37199999/why-nvidia-shares-are-rising"
    print(f"Fetching URL: {url}")
    
    res = await engine.fetch(url, {"screenshot": True})
    print(f"Success: {res.success}")
    print(f"Error: {res.error}")
    print(f"Status: {getattr(res, 'status_code', 'N/A')}")
    
    if res.screenshot_b64:
        # Save screenshot to artifacts directory
        # Conversation ID artifact directory: /home/lazycat/.gemini/antigravity-ide/brain/761ef9f4-f3d9-49e1-b01e-1fb332ecbcfe
        output_dir = "/home/lazycat/.gemini/antigravity-ide/brain/761ef9f4-f3d9-49e1-b01e-1fb332ecbcfe"
        os.makedirs(output_dir, exist_ok=True)
        img_path = os.path.join(output_dir, "benzinga_debug.png")
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(res.screenshot_b64))
        print(f"Screenshot saved to {img_path}")
        
    if res.content:
        print(f"Content Length: {len(res.content)}")
        print(f"First 500 chars of content:\n{res.content[:500]}")
    else:
        print("No content returned.")
        
    await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
