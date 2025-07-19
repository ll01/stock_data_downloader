import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import websockets
from websockets.asyncio.server import ServerConnection
from typing import Dict, List, Any

from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.trading_system import TradingSystem
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import TestExchange
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.websocket_server.stream_processor import StreamProcessor
from stock_data_downloader.models import TickerConfig, HestonConfig


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection"""
    websocket = MagicMock(spec=ServerConnection)
    websocket.remote_address = ("127.0.0.1", 12345)
    websocket.send = AsyncMock()
    websocket.recv = AsyncMock()
    websocket.close = AsyncMock()
    return websocket


@pytest.fixture
def backtest_trading_system():
    """Create a trading system with BacktestDataSource"""
    ticker_configs = {
        "GOOG": TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5))
    }
    global_config = {
        "backtest_model_type": "heston",
        "start_prices": {"GOOG": 2800.0},
        "timesteps": 3,
        "interval": 1.0/252,
        "seed": 42
    }
    
    data_source = BacktestDataSource(ticker_configs, global_config)
    portfolio = Portfolio(initial_cash=100000.0)
    exchange = TestExchange(portfolio=portfolio)
    
    return TradingSystem(
        exchange=exchange,
        portfolio=portfolio,
        data_source=data_source
    )


class TestSimulationEndHandling:
    """Test proper handling of simulation end events"""
    
    @pytest.mark.asyncio
    async def test_simulation_end_propagation(self, backtest_trading_system, mock_websocket):
        """Test that simulation end events are properly propagated to clients"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        server = WebSocketServer(
            trading_system=backtest_trading_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        # Add connection
        await connection_manager.add_connection(mock_websocket)
        
        # Mock the data generation to immediately send simulation end
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator():
                # Empty generator - will immediately trigger simulation end
                if False:
                    yield
            
            mock_gen.return_value = mock_generator()
            
            # Start real-time processing
            task = asyncio.create_task(server.run_realtime())
            
            # Wait for processing
            await asyncio.sleep(0.1)
            
            # Verify simulation end was sent to client
            sent_messages = [json.loads(call[0][0]) for call in mock_websocket.send.call_args_list]
            simulation_end_messages = [msg for msg in sent_messages if msg.get("type") == "simulation_end"]
            
            assert len(simulation_end_messages) == 1
            
            # Clean up
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    @pytest.mark.asyncio
    async def test_simulation_end_with_error(self, backtest_trading_system, mock_websocket):
        """Test that simulation end events with errors are properly handled"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        server = WebSocketServer(
            trading_system=backtest_trading_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        # Add connection
        await connection_manager.add_connection(mock_websocket)
        
        # Directly trigger simulation end with error
        await backtest_trading_system.data_source._notify_callback({
            "type": "simulation_end",
            "error": "Test error message"
        })
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Verify error message was sent to client
        sent_messages = [json.loads(call[0][0]) for call in mock_websocket.send.call_args_list]
        error_messages = [msg for msg in sent_messages if msg.get("type") == "simulation_end" and "error" in msg]
        
        assert len(error_messages) == 1
        assert "Test error message" in error_messages[0]["error"]
    
    @pytest.mark.asyncio
    async def test_reconnection_after_simulation_end(self, backtest_trading_system, mock_websocket):
        """Test that system can reconnect after simulation end"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        server = WebSocketServer(
            trading_system=backtest_trading_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        # Add connection
        await connection_manager.add_connection(mock_websocket)
        
        # First run with simulation end
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator():
                yield [{"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}]
                # End of simulation
            
            mock_gen.return_value = mock_generator()
            
            # Start real-time processing
            task = asyncio.create_task(server.run_realtime())
            
            # Wait for processing
            await asyncio.sleep(0.1)
            
            # Verify simulation end was sent
            sent_messages = [json.loads(call[0][0]) for call in mock_websocket.send.call_args_list]
            simulation_end_messages = [msg for msg in sent_messages if msg.get("type") == "simulation_end"]
            assert len(simulation_end_messages) == 1
            
            # Clean up
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Reset mock for second run
        mock_websocket.send.reset_mock()
        
        # Reset simulation and reconnect
        await server.reset()
        
        # Mock generator for second run
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator2():
                yield [{"ticker": "GOOG", "close": 2900.0, "timestamp": "2023-01-02T00:00:00"}]
                # End of simulation
            
            mock_gen.return_value = mock_generator2()
            
            # Start real-time processing again
            task = asyncio.create_task(server.run_realtime())
            
            # Wait for processing
            await asyncio.sleep(0.1)
            
            # Verify new data was sent
            sent_messages = [json.loads(call[0][0]) for call in mock_websocket.send.call_args_list]
            price_messages = [msg for msg in sent_messages if msg.get("type") == "price_update"]
            assert len(price_messages) > 0
            
            # Clean up
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    @pytest.mark.asyncio
    async def test_stream_processor_simulation_end_handling(self):
        """Test StreamProcessor handling of simulation end events"""
        processor = StreamProcessor()
        received_events = []
        
        async def subscriber(data):
            received_events.append(data)
        
        processor.subscribe(subscriber)
        await processor.start()
        
        # Send normal data
        await processor.ingest([{"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}])
        
        # Send simulation end event
        await processor.ingest({"type": "simulation_end"})
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        await processor.stop()
        
        # Verify both normal data and simulation end were processed
        assert len(received_events) == 2
        assert isinstance(received_events[0], list)  # Normal data
        assert isinstance(received_events[1], dict)  # Simulation end event
        assert received_events[1].get("type") == "simulation_end"