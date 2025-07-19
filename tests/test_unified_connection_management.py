import asyncio
import json
import pytest
import pytest_asyncio
import websockets
from unittest.mock import AsyncMock, MagicMock, patch

from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager


@pytest_asyncio.fixture
async def connection_manager():
    """Create a ConnectionManager instance for testing."""
    # Create with health check disabled for testing
    manager = ConnectionManager(
        max_in_flight_messages=5, 
        max_error_threshold=3,
        start_health_check=False  # Disable health check for tests
    )
    
    # Mock the _sender_task to directly send messages for testing
    async def mock_sender_task(websocket, queue):
        message = await queue.get()
        await websocket.send(message)
        queue.task_done()
    
    # Store the original method
    original_create_task = asyncio.create_task
    
    # Replace asyncio.create_task with a version that just runs the coroutine
    def patched_create_task(coro):
        if "sender_task" in str(coro):
            # Don't create a task for sender_task, just return a done future
            fut = asyncio.Future()
            fut.set_result(None)
            return fut
        return original_create_task(coro)
    
    # Apply the patches
    with patch('asyncio.create_task', side_effect=patched_create_task):
        yield manager
    
    # Clean up
    connections = list(manager.connections)
    for conn in connections:
        try:
            await manager.remove_connection(conn)
        except:
            pass


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    mock = AsyncMock()
    mock.remote_address = ("127.0.0.1", 12345)
    mock.request_headers = {"User-Agent": "Test Client"}
    return mock


@pytest.mark.asyncio
async def test_add_connection(connection_manager, mock_websocket):
    """Test adding a new connection."""
    # Add a connection
    await connection_manager.add_connection(mock_websocket)
    
    # Verify connection was added
    assert mock_websocket in connection_manager.connections
    assert mock_websocket in connection_manager.connection_queues
    assert mock_websocket in connection_manager.error_counts
    assert mock_websocket in connection_manager.connection_info
    
    # Verify connection info was properly initialized
    connection_info = connection_manager.connection_info[mock_websocket]
    assert "connected_at" in connection_info
    assert "client_id" in connection_info
    assert connection_info["remote_address"] == mock_websocket.remote_address
    assert connection_info["messages_sent"] == 0
    assert connection_info["user_agent"] == "Test Client"
    
    # Verify statistics were updated
    assert connection_manager.stats["total_connections"] == 1
    assert connection_manager.stats["active_connections"] == 1
    
    # Verify welcome message was queued (not necessarily sent yet)
    assert connection_manager.connection_queues[mock_websocket].qsize() > 0


@pytest.mark.asyncio
async def test_remove_connection(connection_manager, mock_websocket):
    """Test removing a connection."""
    # Add a connection first
    await connection_manager.add_connection(mock_websocket)
    
    # Reset the mock to clear the welcome message call
    mock_websocket.send.reset_mock()
    
    # Remove the connection
    await connection_manager.remove_connection(mock_websocket)
    
    # Verify connection was removed
    assert mock_websocket not in connection_manager.connections
    assert mock_websocket not in connection_manager.connection_queues
    assert mock_websocket not in connection_manager.error_counts
    assert mock_websocket not in connection_manager.connection_info
    
    # Verify statistics were updated
    assert connection_manager.stats["active_connections"] == 0
    
    # Verify websocket was closed
    mock_websocket.close.assert_called_once()


@pytest.mark.asyncio
async def test_send_message(connection_manager, mock_websocket):
    """Test sending a message to a specific client."""
    # Add a connection
    await connection_manager.add_connection(mock_websocket)
    
    # Clear the queue of the welcome message
    while not connection_manager.connection_queues[mock_websocket].empty():
        await connection_manager.connection_queues[mock_websocket].get()
        connection_manager.connection_queues[mock_websocket].task_done()
    
    # Reset the mock to clear the welcome message call
    mock_websocket.send.reset_mock()
    
    # Send a test message
    test_payload = {"test": "data"}
    await connection_manager.send(mock_websocket, "test_message", test_payload)
    
    # Verify message was queued (not sent directly)
    # The actual send happens in the _sender_task
    assert connection_manager.connection_queues[mock_websocket].qsize() == 1


@pytest.mark.asyncio
async def test_broadcast_to_all(connection_manager):
    """Test broadcasting a message to all clients."""
    # Create multiple mock websockets
    mock_websocket1 = AsyncMock()
    mock_websocket1.remote_address = ("127.0.0.1", 12345)
    mock_websocket2 = AsyncMock()
    mock_websocket2.remote_address = ("127.0.0.1", 12346)
    
    # Add connections
    await connection_manager.add_connection(mock_websocket1)
    await connection_manager.add_connection(mock_websocket2)
    
    # Clear the queues of welcome messages
    while not connection_manager.connection_queues[mock_websocket1].empty():
        await connection_manager.connection_queues[mock_websocket1].get()
        connection_manager.connection_queues[mock_websocket1].task_done()
    
    while not connection_manager.connection_queues[mock_websocket2].empty():
        await connection_manager.connection_queues[mock_websocket2].get()
        connection_manager.connection_queues[mock_websocket2].task_done()
    
    # Reset mocks to clear welcome message calls
    mock_websocket1.send.reset_mock()
    mock_websocket2.send.reset_mock()
    
    # Broadcast a test message
    test_payload = {"test": "broadcast"}
    await connection_manager.broadcast_to_all("test_broadcast", test_payload)
    
    # Verify message was queued for both connections
    assert connection_manager.connection_queues[mock_websocket1].qsize() == 1
    assert connection_manager.connection_queues[mock_websocket2].qsize() == 1


@pytest.mark.asyncio
async def test_broadcast_by_filter(connection_manager):
    """Test broadcasting a message to filtered clients."""
    # Create multiple mock websockets with different metadata
    mock_websocket1 = AsyncMock()
    mock_websocket1.remote_address = ("127.0.0.1", 12345)
    mock_websocket2 = AsyncMock()
    mock_websocket2.remote_address = ("127.0.0.1", 12346)
    
    # Add connections
    await connection_manager.add_connection(mock_websocket1)
    await connection_manager.add_connection(mock_websocket2)
    
    # Clear the queues of welcome messages
    while not connection_manager.connection_queues[mock_websocket1].empty():
        await connection_manager.connection_queues[mock_websocket1].get()
        connection_manager.connection_queues[mock_websocket1].task_done()
    
    while not connection_manager.connection_queues[mock_websocket2].empty():
        await connection_manager.connection_queues[mock_websocket2].get()
        connection_manager.connection_queues[mock_websocket2].task_done()
    
    # Modify connection info for testing filter
    connection_manager.connection_info[mock_websocket1]["group"] = "group1"
    connection_manager.connection_info[mock_websocket2]["group"] = "group2"
    
    # Reset mocks to clear welcome message calls
    mock_websocket1.send.reset_mock()
    mock_websocket2.send.reset_mock()
    
    # Define filter function
    def filter_group1(conn_info):
        return conn_info.get("group") == "group1"
    
    # Broadcast a test message with filter
    test_payload = {"test": "filtered_broadcast"}
    await connection_manager.broadcast_by_filter("test_broadcast", test_payload, filter_group1)
    
    # Verify message was queued only for the filtered connection
    assert connection_manager.connection_queues[mock_websocket1].qsize() == 1
    assert connection_manager.connection_queues[mock_websocket2].qsize() == 0


@pytest.mark.asyncio
async def test_standardized_message_format(connection_manager, mock_websocket):
    """Test that messages are formatted consistently for different data types."""
    # Add a connection
    await connection_manager.add_connection(mock_websocket)
    
    # Clear the queue of the welcome message
    while not connection_manager.connection_queues[mock_websocket].empty():
        await connection_manager.connection_queues[mock_websocket].get()
        connection_manager.connection_queues[mock_websocket].task_done()
    
    # Reset the mock to clear the welcome message call
    mock_websocket.send.reset_mock()
    
    # Test regular message
    await connection_manager.send(mock_websocket, "test_message", {"data": "value"})
    regular_message = await connection_manager.connection_queues[mock_websocket].get()
    regular_parsed = json.loads(regular_message)
    
    # Test price update message
    await connection_manager.send(mock_websocket, "price_update", {"ticker": "BTC", "close": 50000})
    price_message = await connection_manager.connection_queues[mock_websocket].get()
    price_parsed = json.loads(price_message)
    
    # Test simulation end message
    await connection_manager.send(mock_websocket, "simulation_end", {"reason": "completed"})
    sim_end_message = await connection_manager.connection_queues[mock_websocket].get()
    sim_end_parsed = json.loads(sim_end_message)
    
    # Verify consistent format across message types
    assert "type" in regular_parsed
    assert "timestamp" in regular_parsed
    assert regular_parsed["type"] == "test_message"
    
    assert "type" in price_parsed
    assert "timestamp" in price_parsed
    assert price_parsed["type"] == "price_update"
    
    assert "type" in sim_end_parsed
    assert "timestamp" in sim_end_parsed
    assert sim_end_parsed["type"] == "simulation_end"
    assert "reason" in sim_end_parsed


@pytest.mark.asyncio
async def test_error_handling(connection_manager, mock_websocket):
    """Test error handling and connection cleanup on errors."""
    # Add a connection
    await connection_manager.add_connection(mock_websocket)
    
    # Simulate errors
    for _ in range(3):
        connection_manager.increment_error_count(mock_websocket)
    
    # Verify error count
    assert connection_manager.get_error_count(mock_websocket) == 3
    
    # Simulate one more error to exceed threshold
    connection_manager.increment_error_count(mock_websocket)
    
    # Verify error count exceeds threshold
    assert connection_manager.get_error_count(mock_websocket) > connection_manager.MAX_ERROR_THRESHOLD


@pytest.mark.asyncio
async def test_connection_stats(connection_manager, mock_websocket):
    """Test connection statistics tracking."""
    # Add a connection
    await connection_manager.add_connection(mock_websocket)
    
    # Get stats
    stats = connection_manager.get_connection_stats()
    
    # Verify stats
    assert stats["active_connections"] == 1
    assert stats["total_connections"] == 1
    assert "uptime_seconds" in stats
    assert "messages_per_second" in stats


@pytest.mark.asyncio
async def test_shutdown(connection_manager, mock_websocket):
    """Test graceful shutdown."""
    # Add a connection
    await connection_manager.add_connection(mock_websocket)
    
    # Reset the mock to clear the welcome message call
    mock_websocket.send.reset_mock()
    
    # Shutdown
    await connection_manager.shutdown()
    
    # Verify all connections were closed
    assert len(connection_manager.connections) == 0
    
    # In the actual implementation, the shutdown message is queued but not necessarily sent
    # since the _sender_task is mocked in tests. We just verify the connection was removed.
    assert mock_websocket not in connection_manager.connections