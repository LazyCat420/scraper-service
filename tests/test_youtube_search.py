import asyncio
import pytest
import json
import os
import sys
from fastapi.testclient import TestClient

# Add app directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.youtube_collector import YouTubeCollector
from app.main import app


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

async def test_youtube_collector_search():
    print("Testing YouTubeCollector.search()...")
    collector = YouTubeCollector()
    
    # Run query for "garden"
    results = await collector.search("garden", max_results=3, require_transcript=False)
    
    print(f"Retrieved {len(results)} videos.")
    assert len(results) > 0, "No results returned!"
    
    for idx, video in enumerate(results):
        print(f"\nVideo {idx + 1}:")
        print(f"  ID: {video.video_id}")
        print(f"  Title: {video.title}")
        print(f"  Channel: {video.channel}")
        print(f"  Published: {video.published_at}")
        
        # Verify schema
        assert video.video_id, "Missing video_id"
        assert video.title, "Missing title"
        assert video.channel, "Missing channel"

def test_api_collect_endpoint():
    print("\nTesting FastAPI /collect endpoint...")
    client = TestClient(app)
    
    # Test POST request to /collect
    payload = {
        "source": "youtube",
        "query": "garden",
        "limit": 3,
        "days_back": 0,
        "require_transcript": False,
        "stream": False
    }
    
    response = client.post("/collect", json=payload)
    print(f"Response status code: {response.status_code}")
    assert response.status_code == 200, f"Request failed: {response.text}"
    
    data = response.json()
    assert data["source"] == "youtube", "Wrong source in response"
    assert "items" in data, "Missing items list in response"
    assert len(data["items"]) > 0, "Items list is empty"
    
    print(f"API successfully returned {len(data['items'])} items.")
    for idx, item in enumerate(data["items"]):
        print(f"  - Item {idx + 1}: {item['title']} (ID: {item['video_id']}) by {item['channel']}")

if __name__ == "__main__":
    # Run collector search
    asyncio.run(test_youtube_collector_search())
    
    # Run API endpoint test
    test_api_collect_endpoint()
    
    print("\nAll tests completed successfully!")
