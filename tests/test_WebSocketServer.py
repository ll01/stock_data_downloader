import pytest
import asyncio
from unittest.mock import MagicMock, patch
from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.models import AppConfig, DataSourceConfig, BacktestDataSourceConfig

@pytest.mark.asyncio
async def test_synchronous_backtest_mode():
    # Setup config with backtest_mode = "synchronous"
    config = AppConfig(
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
    message_handler = MagicMock()
    
    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri="ws://localhost:8000"
    )
    
    # Mock websocket connection
    websocket = MagicMock()
    
    # Start the server
    task = asyncio.create_task(server.websocket_server(websocket))
    
    # Wait a bit to let the server start
    await asyncio.sleep(0.1)
    
    # Check that automatic streaming is not started
    assert not trading_system.data_source.subscribe_realtime_data.called
    
    # Simulate a next_tick request
    message_handler.handle_message.return_value = MagicMock(
        result_type="price_update",
        payload=[{"ticker": "AAPL", "close": 101, "timestamp": "2023-01-01T00:00:00"}]
    )
    
    # Process the next_tick message
    await server._process_client_message(websocket)
    
    # Check that get_next_bar was called
    assert trading_system.data_source.get_next_bar.called
    
    # Cleanup
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)