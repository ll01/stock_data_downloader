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
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource
from stock_data_downloader.websocket_server.stream_processor import StreamProcessor
from stock_data_downloader.models import TickerConfig, HestonConfig, GBMConfig


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


@pytest.fixture
def hyperliquid_trading_system():
    """Create a trading system with HyperliquidDataSource"""
    config = {"api_key": "test", "secret": "test"}
    tickers = ["BTC", "ETH"]
    
    with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager'):
        data_source = HyperliquidDataSource(config, tickers=tickers)
        portfolio = Portfolio(initial_cash=100000.0)
        exchange = TestExchange(portfolio=portfolio)
        
        return TradingSystem(
            exchange=exchange,
            portfolio=portfolio,
            data_source=data_source
        )


class TestEndToEndDataFlow:
    """Test complete data flow from source to WebSocket clients"""
    
    @pytest.mark.asyncio
    async def test_backtest_to_websocket_flow(self, backtest_trading_system, mock_websocket):
        """Test complete flow from BacktestDataSource to WebSocket client"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        server = WebSocketServer(
            trading_system=backtest_trading_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        # Mock the data generation
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator():
                yield [{"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}]
                yield [{"ticker": "GOOG", "close": 2860.0, "timestamp": "2023-01-01T00:01:00"}]
            
            mock_gen.return_value = mock_generator()
            
            # Add connection
            await connection_manager.add_connection(mock_websocket)
            
            # Start the real-time data flow
            await server.run_realtime()
            
            # Wait a bit for processing
            await asyncio.sleep(0.1)
            
            # Verify WebSocket received messages
            assert mock_websocket.send.called
            
            # Check that messages were sent through the connection manager
            sent_calls = mock_websocket.send.call_args_list
            assert len(sent_calls) > 0
            
            # Verify message format
            for call in sent_calls:
                message_str = call[0][0]
                message = json.loads(message_str)
                assert "type" in message
                
                if message["type"] == "price_update":
                    assert "data" in message
                elif message["type"] == "simulation_end":
                    # Simulation end message should be present
                    pass

    @pytest.mark.asyncio
    async def test_hyperliquid_to_websocket_flow(self, hyperliquid_trading_system, mock_websocket):
        """Test complete flow from HyperliquidDataSource to WebSocket client"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        server = WebSocketServer(
            trading_system=hyperliquid_trading_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        # Add connection
        await connection_manager.add_connection(mock_websocket)
        
        # Simulate WebSocket message from Hyperliquid
        mock_message = {
            "channel": "candle",
            "data": {
                "T": 1640995200000,
                "s": "BTC",
                "o": "50000.0",
                "h": "51000.0",
                "l": "49000.0",
                "c": "50500.0",
                "v": "10.5"
            }
        }
        
        # Trigger the message handling
        hyperliquid_trading_system.data_source._handle_ws_message(mock_message)
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Verify message was processed and sent
        assert mock_websocket.send.called

    @pytest.mark.asyncio
    async def test_stream_processor_integration(self):
        """Test StreamProcessor with different data source types"""
        processor = StreamProcessor()
        received_data = []
        
        async def subscriber(data):
            received_data.append(data)
        
        processor.subscribe(subscriber)
        await processor.start()
        
        # Test with backtest-style data
        backtest_data = [
            {"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}
        ]
        await processor.ingest(backtest_data)
        
        # Test with Hyperliquid-style data
        hyperliquid_data = [
            {
                "ticker": "BTC",
                "timestamp": "2023-01-01T00:01:00",
                "open": 50000.0,
                "high": 51000.0,
                "low": 49000.0,
                "close": 50500.0,
                "volume": 10.5
            }
        ]
        await processor.ingest(hyperliquid_data)
        
        # Test with mixed field naming
        mixed_data = [
            {"symbol": "ETH", "close": 3000.0, "timestamp": "2023-01-01T00:02:00"}
        ]
        await processor.ingest(mixed_data)
        
        # Test simulation end event
        await processor.ingest({"type": "simulation_end"})
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        await processor.stop()
        
        # Verify all data was processed
        assert len(received_data) >= 4  # 3 data batches + 1 simulation end
        
        # Verify data normalization
        for data in received_data:
            if isinstance(data, list) and len(data) > 0:
                tick = data[0]
                assert "ticker" in tick
                assert "timestamp" in tick
                assert "close" in tick
                
        # Verify simulation end event was passed through
        simulation_end_events = [d for d in received_data if isinstance(d, dict) and d.get("type") == "simulation_end"]
        assert len(simulation_end_events) == 1
        
        # Verify market data cache was updated
        assert "GOOG" in processor.market_data_cache
        assert "BTC" in processor.market_data_cache
        assert "ETH" in processor.market_data_cache

    @pytest.mark.asyncio
    async def test_connection_manager_broadcast(self, mock_websocket):
        """Test ConnectionManager broadcasting to multiple clients"""
        connection_manager = ConnectionManager()
        
        # Create multiple mock connections
        mock_websocket2 = MagicMock(spec=ServerConnection)
        mock_websocket2.remote_address = ("127.0.0.1", 12346)
        mock_websocket2.send = AsyncMock()
        
        # Add connections
        await connection_manager.add_connection(mock_websocket)
        await connection_manager.add_connection(mock_websocket2)
        
        # Broadcast message
        test_payload = [{"ticker": "TEST", "close": 100.0}]
        await connection_manager.broadcast_to_all("price_update", test_payload)
        
        # Wait for message processing
        await asyncio.sleep(0.1)
        
        # Verify both connections received the message
        assert mock_websocket.send.called
        assert mock_websocket2.send.called

    @pytest.mark.asyncio
    async def test_data_source_switching(self, mock_websocket):
        """Test switching between different data sources"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        # Start with backtest system
        backtest_system = await self._create_backtest_system()
        server = WebSocketServer(
            trading_system=backtest_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        await connection_manager.add_connection(mock_websocket)
        
        # Test backtest data flow
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator():
                yield [{"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}]
            
            mock_gen.return_value = mock_generator()
            
            # Start real-time processing
            task = asyncio.create_task(server.run_realtime())
            await asyncio.sleep(0.1)
            task.cancel()
            
            # Verify backtest data was processed
            assert mock_websocket.send.called
            
        # Reset for next test
        mock_websocket.send.reset_mock()
        
        # Switch to Hyperliquid system
        with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager'):
            hyperliquid_system = await self._create_hyperliquid_system()
            server.trading_system = hyperliquid_system
            
            # Simulate Hyperliquid message
            mock_message = {
                "channel": "candle",
                "data": {
                    "T": 1640995200000,
                    "s": "BTC",
                    "o": "50000.0",
                    "h": "51000.0",
                    "l": "49000.0",
                    "c": "50500.0",
                    "v": "10.5"
                }
            }
            
            hyperliquid_system.data_source._handle_ws_message(mock_message)
            await asyncio.sleep(0.1)
            
            # Verify Hyperliquid data was processed
            assert mock_websocket.send.called

    async def _create_backtest_system(self):
        """Helper to create backtest trading system"""
        ticker_configs = {
            "GOOG": TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5))
        }
        global_config = {
            "backtest_model_type": "heston",
            "start_prices": {"GOOG": 2800.0},
            "timesteps": 2,
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

    async def _create_hyperliquid_system(self):
        """Helper to create Hyperliquid trading system"""
        config = {"api_key": "test", "secret": "test"}
        tickers = ["BTC"]
        
        data_source = HyperliquidDataSource(config, tickers=tickers)
        portfolio = Portfolio(initial_cash=100000.0)
        exchange = TestExchange(portfolio=portfolio)
        
        return TradingSystem(
            exchange=exchange,
            portfolio=portfolio,
            data_source=data_source
        )


class TestErrorHandlingIntegration:
    """Test error handling in the integrated system"""
    
    @pytest.mark.asyncio
    async def test_websocket_disconnection_handling(self, backtest_trading_system):
        """Test handling of WebSocket disconnections during data streaming"""
        connection_manager = ConnectionManager()
        
        # Create mock WebSocket that will disconnect
        mock_websocket = MagicMock(spec=ServerConnection)
        mock_websocket.remote_address = ("127.0.0.1", 12345)
        mock_websocket.send = AsyncMock(side_effect=websockets.ConnectionClosed(None, None))
        
        await connection_manager.add_connection(mock_websocket)
        
        # Try to broadcast - should handle disconnection gracefully
        await connection_manager.broadcast_to_all("test", {"data": "test"})
        
        # Connection should be removed
        assert mock_websocket not in connection_manager.connections

    @pytest.mark.asyncio
    async def test_data_source_error_recovery(self, mock_websocket):
        """Test recovery from data source errors"""
        connection_manager = ConnectionManager()
        message_handler = MessageHandler()
        
        # Create system with failing data source
        ticker_configs = {
            "GOOG": TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5))
        }
        global_config = {
            "backtest_model_type": "invalid_type",  # This will cause an error
            "start_prices": {"GOOG": 2800.0},
            "timesteps": 2,
            "interval": 1.0/252
        }
        
        data_source = BacktestDataSource(ticker_configs, global_config)
        portfolio = Portfolio(initial_cash=100000.0)
        exchange = TestExchange(portfolio=portfolio)
        trading_system = TradingSystem(exchange=exchange, portfolio=portfolio, data_source=data_source)
        
        server = WebSocketServer(
            trading_system=trading_system,
            connection_manager=connection_manager,
            message_handler=message_handler,
            uri="ws://localhost:8000"
        )
        
        await connection_manager.add_connection(mock_websocket)
        
        # This should handle the error gracefully
        with pytest.raises(ValueError):  # Expected error from invalid model type
            await server.run_realtime()


class TestPerformanceIntegration:
    """Test performance aspects of the integrated system"""
    
    @pytest.mark.asyncio
    async def test_high_throughput_data_processing(self):
        """Test system performance with high-throughput data"""
        processor = StreamProcessor(max_rate=100)  # Lower rate for testing
        received_count = 0
        
        async def counter_subscriber(data):
            nonlocal received_count
            received_count += 1
        
        processor.subscribe(counter_subscriber)
        await processor.start()
        
        # Send many data points rapidly
        for i in range(50):
            test_data = [{"ticker": f"TEST{i}", "close": 100.0 + i, "timestamp": f"2023-01-01T00:{i:02d}:00"}]
            await processor.ingest(test_data)
        
        # Wait for processing
        await asyncio.sleep(1.0)
        await processor.stop()
        
        # Should have processed all data (with rate limiting)
        assert received_count > 0
        assert received_count <= 50  # May be less due to rate limiting

    @pytest.mark.asyncio
    async def test_memory_usage_with_long_running_stream(self):
        """Test memory usage doesn't grow unbounded with long-running streams"""
        # This is a basic test - in practice you'd use memory profiling tools
        processor = StreamProcessor()
        
        async def dummy_subscriber(data):
            pass
        
        processor.subscribe(dummy_subscriber)
        await processor.start()
        
        # Process many data points
        for i in range(100):
            test_data = [{"ticker": "TEST", "close": 100.0, "timestamp": f"2023-01-01T00:00:{i:02d}"}]
            await processor.ingest(test_data)
            
            if i % 10 == 0:
                await asyncio.sleep(0.01)  # Allow processing
        
        await processor.stop()
        
        # Cache should not grow unbounded (only keeps latest per ticker)
        assert len(processor.market_data_cache) <= 1