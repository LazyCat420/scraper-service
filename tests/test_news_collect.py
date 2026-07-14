import asyncio
import pytest
import os
import sys

# Add app directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.collectors.news_collector import NewsCollector
from app.core.session_manager import session_manager


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

async def test_rss_collection():
    print("Testing RSS Feed collection...")
    await session_manager.startup()
    collector = NewsCollector()
    
    # Try parsing MarketWatch Top stories
    feed_url = "https://feeds.marketwatch.com/marketwatch/topstories/"
    try:
        articles = await collector.collect_feed("MarketWatch Top", feed_url, scrape_bodies=True)
        print(f"Collected {len(articles)} articles from {feed_url}.")
        for idx, art in enumerate(articles[:5]):
            print(f"\nArticle {idx + 1}:")
            print(f"  ID: {art.id}")
            print(f"  Title: {art.title}")
            print(f"  URL: {art.url}")
            print(f"  Publisher: {art.publisher}")
            print(f"  Summary Length: {len(art.summary)} chars")
            print(f"  Summary Snippet: {art.summary[:150]}...")
    except Exception as e:
        print(f"Error during collection: {e}")
    finally:
        await session_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(test_rss_collection())
