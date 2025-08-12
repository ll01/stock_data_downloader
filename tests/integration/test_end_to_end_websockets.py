import pytest
import asyncio
import websockets
import json
import logging
from unittest.mock import MagicMock, AsyncMock

logger = logging.getLogger(__name__)
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.server import WebSocketServer

@pytest.mark.asyncio
async def test_minimal_websocket_server_lifecycle():
    """Simplified test: just start and shutdown server without client interactions"""
    # Minimal mock trading system
    dummy_trading_system = MagicMock()
    
    # Minimal server components
    connection_manager = ConnectionManager()
    message_handler = MessageHandler()
    
    # Create and start server
    server = WebSocketServer(
        trading_system=dummy_trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri="ws://localhost:0"
    )
    await server.start()
    
    # Shutdown server
    await server.shutdown()
    
    # Test passes if we reach this point without hanging
    assert True

@pytest.fixture
async def end_to_end_server():
    """Fixture that sets up a real WebSocket server for end-to-end testing"""
    # Create mock data source with predictable behavior
    class MockBacktestDataSource:
        def __init__(self):
            self.bars = [
                [{"ticker": "TEST", "timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000}],
                [{"ticker": "TEST", "timestamp": "2025-01-01T00:00:01Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000}]
            ]
            self.client_states = {}
            self.pull_mode = True

        async def get_next_bar_for_client(self, client_id):
            # Initialize state for new clients
            if client_id not in self.client_states:
                self.client_states[client_id] = 0
            
            # Get current index for client
            idx = self.client_states[client_id]
            
            # Return None if no more bars
            if idx >= len(self.bars):
                return None
            
            # Get bar and update state
            bar = self.bars[idx]
            self.client_states[client_id] += 1
            return bar

        async def reset(self, client_id=None):
            if client_id is not None:
                self.client_states[client_id] = 0
            else:
                self.client_states = {}

    # Create trading system with mock data source
    mock_trading_system = MagicMock()
    mock_trading_system.data_source = MockBacktestDataSource()
    mock_trading_system.portfolio = MagicMock()

    # Create server components
    connection_manager = ConnectionManager(max_in_flight_messages=5)
    message_handler = MessageHandler()

    # Use 127.0.0.1 instead of localhost to avoid Windows issues
    server = WebSocketServer(
        trading_system=mock_trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri="ws://127.0.0.1:0"  # OS assigns free port
    )
    
    # Start server
    await server.start()
    
    # Get the actual port the server is listening on
    port = server.get_port()
    logger.info(f"Server started on port {port}")

    try:
        yield (server, port)
    finally:
        # Ensure server is shut down
        await server.shutdown()

@pytest.mark.asyncio
async def test_end_to_end_client_connection_and_data_flow(end_to_end_server):
    """Test full client connection, data flow, and disconnection lifecycle"""
    _, port = end_to_end_server
    
    # Connect client
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        # Request first bar
        await ws.send(json.dumps({"action": "next_bar"}))
        response = json.loads(await ws.recv())
        assert response["type"] == "price_update"
        # Handle both list and single bar responses
        bar_data = response["data"]
        if isinstance(bar_data, list):
            bar = bar_data[0]
        else:
            bar = bar_data
        assert bar["close"] == 101
        
        # Request second bar
        await ws.send(json.dumps({"action": "next_bar"}))
        response = json.loads(await ws.recv())
        bar_data = response["data"]
        if isinstance(bar_data, list):
            bar = bar_data[0]
        else:
            bar = bar_data
        assert bar["close"] == 102
        
        # Reset simulation
        await ws.send(json.dumps({"action": "reset"}))
        response = json.loads(await ws.recv())
        assert response["type"] == "reset"
        
        # Verify reset by getting first bar again
        await ws.send(json.dumps({"action": "next_bar"}))
        response = json.loads(await ws.recv())
        bar_data = response["data"]
        if isinstance(bar_data, list):
            bar = bar_data[0]
        else:
            bar = bar_data
        assert bar["close"] == 101

@pytest.mark.asyncio
async def test_end_to_end_multiple_clients_isolation(end_to_end_server):
    """Test multiple clients receiving independent data streams"""
    _, port = end_to_end_server

    # Connect two clients
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws1, \
               websockets.connect(f"ws://127.0.0.1:{port}") as ws2:

        # Client 1 requests first bar
        await ws1.send(json.dumps({"action": "next_bar"}))
        response1 = json.loads(await ws1.recv())
        bar_data1 = response1["data"]
        if isinstance(bar_data1, list):
            bar1 = bar_data1[0]
        else:
            bar1 = bar_data1
        assert bar1["close"] == 101

        # Client 2 requests first bar
        await ws2.send(json.dumps({"action": "next_bar"}))
        response2 = json.loads(await ws2.recv())
        bar_data2 = response2["data"]
        if isinstance(bar_data2, list):
            bar2 = bar_data2[0]
        else:
            bar2 = bar_data2
        assert bar2["close"] == 101

        # Verify both received first bar

        # Client 1 requests second bar
        await ws1.send(json.dumps({"action": "next_bar"}))
        response1 = json.loads(await ws1.recv())
        bar_data1 = response1["data"]
        if isinstance(bar_data1, list):
            bar1 = bar_data1[0]
        else:
            bar1 = bar_data1
        assert bar1["close"] == 102

        # Client 2 requests second bar
        await ws2.send(json.dumps({"action": "next_bar"}))
        response2 = json.loads(await ws2.recv())
        bar_data2 = response2["data"]
        if isinstance(bar_data2, list):
            bar2 = bar_data2[0]
        else:
            bar2 = bar_data2
        assert bar2["close"] == 102

        # Verify both clients independently advanced to second bar

@pytest.mark.asyncio
async def test_end_to_end_server_reset_broadcast(end_to_end_server):
    """Test server reset broadcasts to all connected clients"""
    server, port = end_to_end_server
    
    # Connect two clients
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws1, \
               websockets.connect(f"ws://127.0.0.1:{port}") as ws2:
        
        # Both clients get first bar
        for ws in [ws1, ws2]:
            await ws.send(json.dumps({"action": "next_bar"}))
            response = json.loads(await ws.recv())
            bar_data = response["data"]
            if isinstance(bar_data, list):
                bar = bar_data[0]
            else:
                bar = bar_data
            assert bar["close"] == 101
        
        # Perform server reset (via direct call)
        await server.reset_server()
        
        # Allow time for reset propagation
        await asyncio.sleep(0.1)
        
        # Verify both clients received reset message
        for ws in [ws1, ws2]:
            response = json.loads(await ws.recv())
            assert response["type"] == "reset"
            
            # Verify next bar is first bar again
            await ws.send(json.dumps({"action": "next_bar"}))
            response = json.loads(await ws.recv())
            bar_data = response["data"]
            if isinstance(bar_data, list):
                bar = bar_data[0]
            else:
                bar = bar_data
            assert bar["close"] == 101

@pytest.mark.asyncio
async def test_end_to_end_oversized_message_rejection(end_to_end_server):
    """Test server rejects oversized client messages"""
    _, port = end_to_end_server
    
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        # Create oversized payload (exceeds 64KB)
        oversized_payload = {"data": "x" * 65537}
        await ws.send(json.dumps(oversized_payload))
        
        # Verify connection is closed with appropriate code
        with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
            await ws.recv()
        
        assert exc_info.value.code == 1009  # Message too big

@pytest.mark.asyncio
async def test_end_to_end_invalid_json_handling(end_to_end_server):
    """Test server handles invalid JSON from client"""
    _, port = end_to_end_server

    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        # Send invalid JSON
        await ws.send("not valid json")

        # Verify error response is received
        response = json.loads(await ws.recv())
        assert response["type"] == "error"
        assert response["data"]["code"] == "INVALID_JSON"
        assert response["data"]["message"] == "Invalid JSON format received"
        
        # Verify connection remains open
        await ws.send(json.dumps({"action": "next_bar"}))
        response = json.loads(await ws.recv())
        assert response["type"] == "price_update"

@pytest.mark.asyncio
async def test_end_to_end_client_disconnect_during_stream(end_to_end_server):
    """Test server handles client disconnect during active streaming"""
    _, port = end_to_end_server
    
    # Connect client and get first bar
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    await ws.send(json.dumps({"action": "next_bar"}))
    response = json.loads(await ws.recv())
    bar_data = response["data"]
    if isinstance(bar_data, list):
        bar = bar_data[0]
    else:
        bar = bar_data
    assert bar["close"] == 101
    
    # Disconnect client
    await ws.close()
    
    # Allow time for cleanup
    await asyncio.sleep(0.1)
    
    # Server should clean up resources without error
    # No explicit assertion needed - test passes if no exceptions

@pytest.mark.asyncio
async def test_end_to_end_concurrent_client_operations(end_to_end_server):
    """Test server handles concurrent requests from multiple clients"""
    _, port = end_to_end_server
    
    async def client_task(client_id):
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            results = []
            for _ in range(2):  # Get 2 bars
                await ws.send(json.dumps({"action": "next_bar"}))
                response = json.loads(await ws.recv())
                bar_data = response["data"]
                if isinstance(bar_data, list):
                    bar = bar_data[0]
                else:
                    bar = bar_data
                results.append(bar["close"])
            return results
    
    # Start multiple concurrent client tasks
    tasks = [asyncio.create_task(client_task(i)) for i in range(5)]
    results = await asyncio.gather(*tasks)
    
    # Verify each client got the expected sequence
    for client_results in results:
        assert client_results == [101, 102]

@pytest.mark.asyncio
async def test_end_to_end_exchange_integration_flow(end_to_end_server):
    """Test full flow including exchange integration points"""
    server, port = end_to_end_server
    
    # Setup mock exchange in trading system
    mock_exchange = MagicMock()
    mock_exchange.place_order = AsyncMock(return_value=[MagicMock(success=True)])
    mock_exchange.get_order_status = AsyncMock(return_value=MagicMock(status="filled"))
    mock_exchange.cancel_order = AsyncMock(return_value=MagicMock(success=True))
    mock_exchange.get_position = AsyncMock(return_value=MagicMock(size=0.001))
    server.trading_system.exchange = mock_exchange
    
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        # Connect and get initial bar
        await ws.send(json.dumps({"action": "next_bar"}))
        response = json.loads(await ws.recv())
        bar_data = response["data"]
        if isinstance(bar_data, list):
            bar = bar_data[0]
        else:
            bar = bar_data
        assert bar["close"] == 101
        
        # Place a test order
        order_request = {
            "action": "order",
            "data": {
                "ticker": "BTC",
                "order_type": "buy",
                "quantity": 0.001,
                "price": 100.0
            }
        }
        await ws.send(json.dumps(order_request))
        response = json.loads(await ws.recv())
        
        # Verify order placement success - response data is a list of order results
        assert response["type"] == "order_confirmation"
        assert isinstance(response["data"], list)
        assert len(response["data"]) > 0
        assert response["data"][0]["success"] is True

@pytest.mark.asyncio
async def test_end_to_end_server_lifecycle_full_cycle(end_to_end_server):
    """Test complete server lifecycle: start → operate → shutdown"""
    server, port = end_to_end_server
    
    # Connect client during operation
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        # Give server time to become ready
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"action": "next_bar"}))
        response = json.loads(await ws.recv())
        bar_data = response["data"]
        if isinstance(bar_data, list):
            bar = bar_data[0]
        else:
            bar = bar_data
        assert bar["close"] == 101
    
    # Shutdown server
    await server.shutdown()
    
    # Attempt to connect after shutdown should fail
    with pytest.raises(OSError):
        await websockets.connect(f"ws://127.0.0.1:{port}")