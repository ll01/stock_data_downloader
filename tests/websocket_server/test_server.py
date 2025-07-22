import asyncio
import json
import pytest
import websockets
from unittest.mock import AsyncMock, MagicMock, patch
from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.models import AppConfig, TickerData
from stock_data_downloader.websocket_server.trading_system import TradingSystem
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler

# Mock data
VALID_TRADE_MESSAGE = json.dumps({
    "action": "place_order",
    "symbol": "AAPL",
    "quantity": 10,
    "price": 150.0
})

INVALID_JSON_MESSAGE = "not a json string"
OVERSIZED_MESSAGE = "a" * 65537  # Exceeds 64KB limit

# Fixtures
@pytest.fixture
def mock_trading_system():
    system = MagicMock(spec=TradingSystem)
    system.data_source = AsyncMock()
    system.data_source.get_historical_data.return_value = []
    system.exchange = AsyncMock()
    return system

@pytest.fixture
def mock_connection_manager():
    manager = MagicMock(spec=ConnectionManager)
    manager.connections = {}
    manager.add_connection = AsyncMock()
    manager.remove_connection = AsyncMock()
    manager.send = AsyncMock()
    manager.broadcast_to_all = AsyncMock()
    manager.increment_error_count = MagicMock(return_value=1)
    return manager

@pytest.fixture
def mock_message_handler():
    handler = MagicMock(spec=MessageHandler)
    handler.handle_message = AsyncMock()
    return handler

@pytest.fixture
def websocket_server(mock_trading_system, mock_connection_manager, mock_message_handler):
    return WebSocketServer(
        trading_system=mock_trading_system,
        connection_manager=mock_connection_manager,
        message_handler=mock_message_handler,
        uri="ws://localhost:8080"
    )

@pytest.fixture
def mock_websocket():
    ws = AsyncMock()
    ws.remote_address = ("127.0.0.1", 12345)
    return ws

# Tests
@pytest.mark.asyncio
async def test_valid_message_processing(websocket_server, mock_websocket, mock_message_handler):
    """Test valid trade message processing"""
    mock_message_handler.handle_message.return_value.payload = {"status": "executed"}

    # Simulate receiving a valid message
    mock_websocket.recv.return_value = VALID_TRADE_MESSAGE

    await websocket_server._process_client_message(mock_websocket)

    # Verify message was processed
    mock_message_handler.handle_message.assert_called_once()
    websocket_server.connection_manager.send.assert_called_once()

@pytest.mark.asyncio
async def test_invalid_json_handling(websocket_server, mock_websocket):
    """Test handling of invalid JSON messages"""
    mock_websocket.recv.return_value = INVALID_JSON_MESSAGE

    await websocket_server._process_client_message(mock_websocket)

    # Verify error was sent
    websocket_server.connection_manager.send.assert_called()
    assert "invalid_json" in str(websocket_server.connection_manager.send.call_args)

@pytest.mark.asyncio
async def test_oversized_message_rejection(websocket_server, mock_websocket):
    """Test rejection of oversized messages"""
    mock_websocket.recv.return_value = OVERSIZED_MESSAGE

    await websocket_server._process_client_message(mock_websocket)

    # Verify connection was closed due to protocol error
    mock_websocket.close.assert_called_once_with(code=1007, reason="Too many protocol errors")

@pytest.mark.asyncio
async def test_order_confirmation_response(websocket_server, mock_websocket, mock_message_handler):
    """Test proper order confirmation response"""
    # Configure mock to return order confirmation
    mock_message_handler.handle_message.return_value.result_type = "order_confirmation"
    mock_message_handler.handle_message.return_value.payload = {"order_id": "12345", "status": "filled"}

    mock_websocket.recv.return_value = VALID_TRADE_MESSAGE

    await websocket_server._process_client_message(mock_websocket)

    # Verify order confirmation was sent
    args, kwargs = websocket_server.connection_manager.send.call_args
    assert args[1] == "order_confirmation"
    assert kwargs["payload"]["status"] == "filled"

@pytest.mark.asyncio
async def test_connection_error_handling(websocket_server, mock_websocket):
    """Test handling of connection errors"""
    # Simulate connection closed with error
    # Create proper Close objects for ConnectionClosedError
    rcvd = websockets.Close(1006, "Abnormal closure")
    sent = websockets.Close(1006, "Abnormal closure")
    mock_websocket.recv.side_effect = websockets.ConnectionClosedError(rcvd, sent)

    await websocket_server._process_client_message(mock_websocket)

    # Verify connection was removed
    websocket_server.connection_manager.remove_connection.assert_called_once_with(mock_websocket)

@pytest.mark.asyncio
async def test_historical_data_sent_on_connect(websocket_server, mock_websocket, mock_trading_system):
    """Test historical data is sent when client connects"""
    # Set up mock historical data
    historical_data = [TickerData(
        ticker="AAPL",
        open=149.0,
        high=151.0,
        low=148.5,
        close=150.0,
        volume=1000000,
        timestamp="123456789"
    )]
    mock_trading_system.data_source.get_historical_data.return_value = historical_data

    await websocket_server.websocket_server(mock_websocket)

    # Verify historical data was sent
    websocket_server.connection_manager.send.assert_called_with(
        mock_websocket, "price_history", historical_data
    )

@pytest.mark.asyncio
async def test_reset_functionality(websocket_server, mock_websocket, mock_message_handler):
    """Test reset functionality when requested"""
    # Configure mock to return reset request
    mock_message_handler.handle_message.return_value.result_type = "reset_requested"

    mock_websocket.recv.return_value = VALID_TRADE_MESSAGE

    await websocket_server._process_client_message(mock_websocket)

    # Verify reset was called
    assert websocket_server.trading_system.portfolio.clear_positions.called
    assert websocket_server.trading_system.data_source.reset.called
    websocket_server.connection_manager.broadcast_to_all.assert_called_with(
        "reset", {"message": "Simulation has been reset."}
    )

@pytest.mark.asyncio
async def test_trade_message_handling(websocket_server, mock_websocket, mock_message_handler):
    """Test server correctly receives trade messages and sends executed confirmation"""
    # Configure mock to return executed confirmation
    mock_message_handler.handle_message.return_value.result_type = "order_confirmation"
    mock_message_handler.handle_message.return_value.payload = {"status": "executed", "order_id": "12345"}

    # Create valid trade message
    trade_message = json.dumps({
        "action": "place_order",
        "symbol": "AAPL",
        "quantity": 10,
        "price": 150.0
    })

    # Simulate receiving trade message
    mock_websocket.recv.return_value = trade_message

    await websocket_server._process_client_message(mock_websocket)

    # Verify message was processed and executed confirmation sent
    mock_message_handler.handle_message.assert_called_once()
    args, kwargs = websocket_server.connection_manager.send.call_args
    assert args[1] == "order_confirmation"
    assert kwargs["payload"]["status"] == "executed"

# New test for unit test requirement
@pytest.mark.asyncio
async def test_server_receives_trade_and_sends_executed(websocket_server, mock_websocket, mock_message_handler):
    """
    Unit Test - Server: Validate the server correctly receives trade messages from a client
    and sends back an "executed" confirmation. Mock client interactions.
    """
    # Configure mock to return executed confirmation
    mock_message_handler.handle_message.return_value.result_type = "order_confirmation"
    mock_message_handler.handle_message.return_value.payload = {"status": "executed"}

    # Create a trade message
    trade_message = json.dumps({
        "action": "place_order",
        "symbol": "AAPL",
        "quantity": 10,
        "price": 150.0
    })

    # Simulate client sending trade message
    mock_websocket.recv.return_value = trade_message

    # Process the message
    await websocket_server._process_client_message(mock_websocket)

    # Verify the server processed the trade message
    mock_message_handler.handle_message.assert_called_once()
    # Verify the server sent back an "executed" confirmation
    args, kwargs = websocket_server.connection_manager.send.call_args
    assert args[1] == "order_confirmation"
    assert "executed" in str(kwargs["payload"])