import asyncio
import pytest
import os
import sys
from fastapi.testclient import TestClient

# Add app directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.reddit_purge_collector import RedditPurgeCollector
from app.core.session_manager import session_manager
from app.main import app


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

async def test_reddit_purge_collector():
    print("Testing RedditPurgeCollector locally...")
    await session_manager.startup()
    collector = RedditPurgeCollector()
    
    try:
        # Run local collect sweep with small limit to check for import/logic errors
        results = await collector.collect(subreddits=["stocks"], limit=2, use_llm=False)
        print(f"Sweep completed. Discovered {len(results)} trending tickers.")
        if results:
            print(f"Top discovered ticker: {results[0]['ticker']} with score {results[0]['score']}")
            assert "ticker" in results[0]
            assert "posts" in results[0]
    except Exception as e:
        print(f"Collector error (unexpected): {e}")
        raise e
    finally:
        await session_manager.shutdown()

def test_api_collect_reddit_purge():
    print("\nTesting FastAPI /collect endpoint for reddit-purge...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(session_manager.startup())
    try:
        with TestClient(app) as client:
            payload = {
                "source": "reddit-purge",
                "subreddits": ["stocks"],
                "limit": 2,
                "use_llm": False,
                "stream": False
            }
            response = client.post("/collect", json=payload)
            print(f"Response status code: {response.status_code}")
            assert response.status_code == 200, f"Request failed: {response.text}"
            
            data = response.json()
            assert data["source"] == "reddit-purge", "Wrong source in response"
            assert "items" in data, "Missing items list in response"
            print(f"API returned {len(data['items'])} items.")
    finally:
        loop.run_until_complete(session_manager.shutdown())
        loop.close()

if __name__ == "__main__":
    asyncio.run(test_reddit_purge_collector())
    test_api_collect_reddit_purge()
    print("\nAll Reddit Purge tests completed successfully!")
