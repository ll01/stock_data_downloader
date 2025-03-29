import asyncio
from datetime import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import websockets
from websockets.exceptions import ConnectionClosedOK

from stock_data_downloader.websocket_server.server import WebSocketServer

@pytest.fixture
def mock_server():
    """Create a test server with minimal configuration"""
    return WebSocketServer(
        uri="ws://localhost:8000",
        start_prices={"AAPL": 150.0},
        stats={"AAPL": MagicMock(mean=0.0001, sd=0.015)},
        interval=1.0,
        generated_prices_count=10
    )

@pytest.mark.asyncio
async def test_connection_management(mock_server):
    """Test adding and removing connections"""
    mock_ws = AsyncMock()
    
    # Test adding connection
    await mock_server.add_connection(mock_ws)
    assert mock_ws in mock_server.connections
    
    # Test removing connection
    await mock_server.remove_connection(mock_ws)
    assert mock_ws not in mock_server.connections

@pytest.mark.asyncio
async def test_message_handling(mock_server):
    """Test handling different message types"""
    mock_ws = AsyncMock()
    mock_server.current_prices = {"AAPL": 155.0}

    # Mock simulate_prices to avoid multiprocessing issues
    with patch(
        "stock_data_downloader.websocket_server.server.simulate_prices",
        return_value={"AAPL": [{"close": 150.0}]},
    ):
        # Test buy order
        buy_msg = {"action": "buy", "ticker": "AAPL", "quantity": 10}
        await mock_server.handle_message(mock_ws, buy_msg)
        mock_ws.send.assert_called_once()

        # Test sell order
        sell_msg = {"action": "sell", "ticker": "AAPL", "quantity": 5}
        await mock_server.handle_message(mock_ws, sell_msg)
        assert mock_ws.send.call_count == 2

        # Test reset (now patched)
        reset_msg = {"action": "reset"}
        await mock_server.handle_message(mock_ws, reset_msg)
        assert mock_ws.send.call_count == 3
        assert mock_server.current_prices["AAPL"] == 150.0  # Verify reset

@pytest.mark.asyncio
async def test_price_emission(mock_server):
    """Test price emission functionality in simulation mode"""
    # Create and configure mock WebSocket
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)
    mock_ws.closed = False
    mock_ws.__aiter__.return_value = []  # No incoming messages

    # Setup test price data
    test_prices = {
        "AAPL": [
            {"open": 150.0, "high": 151.0, "low": 149.5, "close": 150.5, "volume": 1000},
            {"open": 150.5, "high": 152.0, "low": 150.0, "close": 151.5, "volume": 1200}
        ]
    }

    # Configure mock server state
    mock_server.simulation_running = False
    mock_server.simulated_prices = test_prices
    mock_server.current_prices = {"AAPL": 150.0}  # Initial price
    mock_server.connections.add(mock_ws)  # Simulate connected client

    # Mock dependencies
    with patch(
        "stock_data_downloader.websocket_server.server.datetime"
    ) as mock_datetime, patch(
        "stock_data_downloader.websocket_server.server.random.uniform",
        return_value=0.1  # Consistent delay for testing
    ):
        # Freeze time
        test_time = datetime(2023, 1, 1, 12, 0)
        mock_datetime.now.return_value = test_time

        # Run price emission
        emission_task = asyncio.create_task(mock_server.emit_price_ticks(mock_ws))
        
        # Wait for emission (enough time for at least one tick)
        await asyncio.sleep(0.15)
        
        # Cancel the task
        emission_task.cancel()
        try:
            await emission_task
        except asyncio.CancelledError:
            pass

        # Verify prices were sent
        assert mock_ws.send.call_count > 0, "No prices were emitted"
        
        # Verify message structure
        sent_messages = [call.args[0] for call in mock_ws.send.call_args_list]
        for message in sent_messages:
            data = json.loads(message)
            assert isinstance(data, list)
            for tick in data:
                assert "timestamp" in tick
                assert tick["ticker"] == "AAPL"
                assert all(key in tick for key in ["open", "high", "low", "close", "volume"])
                
        # Verify current_prices was updated
        assert mock_server.current_prices["AAPL"] in [150.5, 151.5]  # Should be updated
    
    
    
@pytest.mark.asyncio
async def test_simulation_mode(mock_server):
    """Test simulation mode with immediate disconnection"""
    mock_ws = AsyncMock()
    mock_ws.__aiter__.side_effect = [
        [json.dumps({"action": "buy", "ticker": "AAPL", "quantity": 10})],
        websockets.exceptions.ConnectionClosedOK(None, None)
    ]

    mock_server.realtime = False
    
    with patch(
        "stock_data_downloader.websocket_server.server.simulate_prices",
        return_value={"AAPL": [{"close": 150.0}]}
    ):
        await mock_server.websocket_server(mock_ws)
        
        # Verify basic workflow
        assert mock_ws.send.call_count >= 1
        mock_ws.close.assert_awaited_once()
        assert mock_ws not in mock_server.connections
        
@pytest.mark.asyncio
async def test_realtime_mode(mock_server):
    """Test realtime mode operation"""
    mock_server.realtime = True
    mock_ws = AsyncMock()
    
    # Set up mock to close after first iteration
    mock_ws.__aiter__.side_effect = [[json.dumps({"action": "ping"})], ConnectionClosedOK(None, None)]
    
    with patch.object(mock_server, 'run_realtime', new_callable=AsyncMock) as mock_realtime:
        # No timeout needed since we're forcing closure
        await mock_server.websocket_server(mock_ws)
        
        # Verify realtime task was started
        mock_realtime.assert_called_once()
        
        # Verify proper connection lifecycle
        assert mock_ws not in mock_server.connections
        mock_ws.close.assert_called_once()
        
@pytest.mark.asyncio
async def test_broadcast(mock_server):
    """Test broadcasting to multiple clients"""
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    
    # Add connections
    await mock_server.add_connection(mock_ws1)
    await mock_server.add_connection(mock_ws2)
    
    # Test broadcast
    test_data = {"test": "data"}
    await mock_server.broadcast_to_all(test_data)
    
    # Verify both clients received data
    mock_ws1.send.assert_called_once_with(json.dumps(test_data))
    mock_ws2.send.assert_called_once_with(json.dumps(test_data))
    
@pytest.mark.asyncio
async def test_multiple_connections(mock_server):
    """Test handling multiple concurrent connections"""
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    
    await mock_server.add_connection(mock_ws1)
    await mock_server.add_connection(mock_ws2)
    
    assert len(mock_server.connections) == 2
    await mock_server.remove_connection(mock_ws1)
    assert len(mock_server.connections) == 1
    
@pytest.mark.asyncio
async def test_simulation_restart_protection(mock_server):
    """Test prevention of multiple simulation instances"""
    mock_ws = AsyncMock()
    mock_server.simulation_running = True
    
    await mock_server.emit_price_ticks(mock_ws)
    mock_ws.send.assert_not_called()  # Should skip emission



@pytest.mark.asyncio
async def test_realtime_broadcast(mock_server):
    """Test broadcast to multiple clients in realtime mode"""
    mock_server.realtime = True
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    
    with patch.object(mock_server, 'generate_realtime_prices') as mock_gen:
        mock_gen.return_value = AsyncMock()
        mock_gen.return_value.__aiter__.return_value = [
            [{"ticker": "AAPL", "close": 150.0}]
        ]
        
        await mock_server.add_connection(mock_ws1)
        await mock_server.add_connection(mock_ws2)
        await mock_server.run_realtime()
        
        await asyncio.sleep(0.1)
        mock_ws1.send.assert_awaited()
        mock_ws2.send.assert_awaited()
        
        
@pytest.mark.asyncio
async def test_invalid_message_handling(mock_server):
    """Test handling of malformed messages"""
    mock_ws = AsyncMock()
    mock_ws.__aiter__.side_effect = [
        "not valid json",
        json.dumps({"invalid": "format"}),
        ConnectionClosedOK(None, None)
    ]
    
    await mock_server.websocket_server(mock_ws)
    # Should handle without crashing
    
    
@pytest.mark.asyncio
async def test_order_execution(mock_server):
    """Test order execution flow"""
    mock_ws = AsyncMock()
    mock_server.current_prices = {"AAPL": 150.0}
    
    orders = [
        {"action": "buy", "ticker": "AAPL", "quantity": 10},
        {"action": "sell", "ticker": "AAPL", "quantity": 5},
        {"action": "short", "ticker": "AAPL", "quantity": 3}
    ]
    
    for order in orders:
        await mock_server.handle_message(mock_ws, order)
    
    assert mock_ws.send.call_count == 3

@pytest.mark.asyncio
async def test_unknown_ticker_handling(mock_server):
    """Test orders for non-existent tickers"""
    mock_ws = AsyncMock()
    mock_server.current_prices = {"AAPL": 150.0}
    
    await mock_server.handle_message(
        mock_ws,
        {"action": "buy", "ticker": "UNKNOWN", "quantity": 10}
    )
    
    # Should either handle gracefully or send error response
    mock_ws.send.assert_awaited()
    
@pytest.mark.asyncio
async def test_short_selling_workflow(mock_server):
    """Test complete short selling lifecycle"""
    mock_ws = AsyncMock()
    mock_server.current_prices = {"AAPL": 150.0}
    
    # Test short opening
    await mock_server.handle_message(
        mock_ws,
        {"action": "short", "ticker": "AAPL", "quantity": 10, "price": 420}
    )
    
    # Verify short position opened
    assert "AAPL" in mock_server.portfolio.short_positions
    assert mock_server.portfolio.short_positions["AAPL"][0] == 10
    assert mock_server.portfolio.short_positions["AAPL"][1] == 420
    
    # Test short covering
    await mock_server.handle_message(
        mock_ws,
        {"action": "cover", "ticker": "AAPL", "quantity": 10, "price": 420}
    )
    
    # Verify short position closed
    assert "AAPL" not in mock_server.portfolio.short_positions
    

@pytest.mark.asyncio
async def test_zero_quantity_rejection(mock_server):
    """Test rejection of invalid quantities"""
    mock_ws = AsyncMock()
    mock_server.current_prices = {"AAPL": 150.0}
    
    await mock_server.handle_message(
        mock_ws,
        {"action": "buy", "ticker": "AAPL", "quantity": 0}
    )
    
    response = json.loads(mock_ws.send.call_args[0][0])
    assert response["status"] == "rejected"
    assert "quantity" in response["reason"]

@pytest.mark.asyncio
async def test_missing_ticker_rejection(mock_server):
    """Test rejection of orders missing ticker"""
    mock_ws = AsyncMock()
    
    await mock_server.handle_message(
        mock_ws,
        {"action": "buy", "quantity": 10}  # Missing ticker
    )
    
    response = json.loads(mock_ws.send.call_args[0][0])
    assert response["status"] == "rejected"
    assert "ticker" in response["reason"]