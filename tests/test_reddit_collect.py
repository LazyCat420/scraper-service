import asyncio
import pytest
import os
import sys
from fastapi.testclient import TestClient

# Add app directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.reddit_collector import RedditCollector
from app.core.session_manager import session_manager
from app.main import app


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

async def test_reddit_collector():
    print("Testing RedditCollector...")
    await session_manager.startup()
    collector = RedditCollector()
    
    # Run query for "AMD"
    try:
        results = await collector.search("AMD", subreddits=["stocks"], limit=3)
    finally:
        await session_manager.shutdown()
    
    print(f"Retrieved {len(results)} search results.")
    assert len(results) > 0, "No results returned for search!"
    
    for idx, post in enumerate(results):
        print(f"\nPost {idx + 1}:")
        print(f"  ID: {post.id}")
        print(f"  Title: {post.title}")
        print(f"  Author: {post.author}")
        print(f"  Subreddit: {post.subreddit}")
        
        # Verify schema
        assert post.id, "Missing post.id"
        assert post.title, "Missing post.title"
        assert post.subreddit, "Missing post.subreddit"
        assert post.author, "Missing post.author"

def test_api_collect_reddit():
    print("\nTesting FastAPI /collect endpoint for Reddit...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(session_manager.startup())
    try:
        with TestClient(app) as client:
            # Test POST request to /collect
            payload = {
                "source": "reddit",
                "subreddits": ["stocks"],
                "query": "AMD",
                "limit": 3,
                "stream": False
            }
            
            response = client.post("/collect", json=payload)
            print(f"Response status code: {response.status_code}")
            assert response.status_code == 200, f"Request failed: {response.text}"
            
            data = response.json()
            assert data["source"] == "reddit", "Wrong source in response"
            assert "items" in data, "Missing items list in response"
            assert len(data["items"]) > 0, "Items list is empty"
            
            print(f"API successfully returned {len(data['items'])} items.")
            for idx, item in enumerate(data['items']):
                print(f"  - Item {idx + 1}: {item['title']} (ID: {item['id']}) by {item['author']}")
    finally:
        loop.run_until_complete(session_manager.shutdown())
        loop.close()

import time

if __name__ == "__main__":
    # Run collector tests
    asyncio.run(test_reddit_collector())
    
    print("\nWaiting 60 seconds to cool down rate limits...")
    time.sleep(60)
    
    # Run API endpoint test
    test_api_collect_reddit()
    
    print("\nAll Reddit tests completed successfully!")
