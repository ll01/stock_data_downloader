import pytest
import asyncio
import websockets
from unittest.mock import MagicMock, patch, AsyncMock
from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.models import AppConfig, DataSourceConfig, BacktestDataSourceConfig
from websockets.exceptions import ConnectionClosedOK
from websockets.frames import Close

@pytest.mark.asyncio
async def test_synchronous_backtest_mode():
    from unittest.mock import MagicMock
    # Setup config with backtest_mode = "synchronous"
    from stock_data_downloader.models import ServerConfig, ExchangeConfig

    # Create minimal valid ServerConfig
    server_cfg = ServerConfig()
    # Create minimal valid ExchangeConfig
    from stock_data_downloader.models import TestExchangeConfig
    test_exchange_config = TestExchangeConfig(type="test")
    exchange_cfg = ExchangeConfig(exchange=test_exchange_config)

    config = AppConfig(
        server=server_cfg,
        exchange=exchange_cfg,
        data_source=DataSourceConfig(
            source_type="backtest",
            config=BacktestDataSourceConfig(
                    source_type="backtest",
                    backtest_model_type="gbm",
                    timesteps=10,
                    interval=1,
                    seed=42,
                    start_prices={"AAPL": 100},
                    ticker_configs={}
                )
        ),
        initial_cash=10000
    )
    
    # Mock dependencies
    trading_system = MagicMock()
    connection_manager = MagicMock()
    # Make remove_connection awaitable
    connection_manager.remove_connection = AsyncMock(return_value=None)
    message_handler = MagicMock()
    
    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri="ws://localhost:8000"
    )
    
    # Make websocket instance appear to be a ServerConnection type for type checkers
    class AsyncMockWebSocket:
        """A simple asynchronous mock websocket that mimics the ServerConnection interface enough for testing"""
        def __init__(self):
            self.remote_address = "mock_client"
            self.first_message = True
        async def recv(self):
            if self.first_message:
                self.first_message = False
                return '{"action": "next_tick"}'
            raise ConnectionClosedOK(Close(1000, "Test closed"), None)
        async def send(self, message):
            return None
        async def close(self, code=1000, reason=""):
            return None

    websocket = AsyncMockWebSocket()  # type: ignore[arg-type]
    
    # Start the server
    task = asyncio.create_task(server.websocket_server(websocket))  # type: ignore[arg-type]
    
    # Wait until the server has added the connection (deterministic readiness)
    await pytest.wait_for(lambda: connection_manager.add_connection.called, timeout=2.0)
    
    # Check that automatic streaming is not started
    assert not trading_system.data_source.subscribe_realtime_data.called
    
    # Simulate a next_tick request
    message_handler.handle_message.return_value = MagicMock(
        result_type="price_update",
        payload=[{"ticker": "AAPL", "close": 101, "timestamp": "2023-01-01T00:00:00"}]
    )
    
    # Process the next_tick message
    await server._process_client_message(websocket)  # type: ignore[arg-type]
    
    # Check that get_next_bar_for_client was called
    assert trading_system.data_source.get_next_bar_for_client.called
    
    # Cleanup
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)