import pytest
from unittest.mock import patch, MagicMock


# All tests in this module hit live external sites
pytestmark = pytest.mark.live

@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_stocktwits_collect_success(mock_get):
    from app.collectors.stocktwits_collector import StockTwitsCollector
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "messages": [
            {
                "id": 12345,
                "body": "AAPL is looking bullish today!",
                "created_at": "2026-06-15T18:00:00Z",
                "user": {
                    "username": "bullish_trader",
                    "name": "Bullish Trader",
                    "followers": 120
                },
                "sentiment": {
                    "basic": "Bullish"
                }
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp
    
    collector = StockTwitsCollector()
    messages = await collector.get_symbol_stream("AAPL")
    
    assert len(messages) == 1
    assert messages[0].username == "bullish_trader"
    assert messages[0].sentiment == "Bullish"
    assert messages[0].body == "AAPL is looking bullish today!"
