import pytest
from unittest.mock import AsyncMock
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager

@pytest.mark.asyncio
async def test_handle_message_price_update():
    mh = MessageHandler()
    ts = AsyncMock()
    # Ensure the data_source exists and is in pull mode so next_bar is allowed
    ts.data_source = AsyncMock()
    ts.data_source.pull_mode = True
    ts.data_source.get_next_bar_for_client = AsyncMock(return_value=[{"ticker": "AAPL", "close": 123}])
    cm = ConnectionManager()

    result = await mh.handle_message({"action": "next_bar", "_client_id": "client-1"}, AsyncMock(), ts.data_source, cm)
    assert result.result_type == "price_update"
    assert isinstance(result.payload, list)
    assert result.payload[0]["close"] == 123

@pytest.mark.asyncio
async def test_handle_invalid_message():
    mh = MessageHandler()
    ts = AsyncMock()
    ts.data_source = AsyncMock()
    cm = ConnectionManager()
    result = await mh.handle_message({"action": "invalid"}, AsyncMock(), ts.data_source, cm)
    assert result.result_type == "trade_rejection"
    assert "invalid action" in result.payload["reason"]