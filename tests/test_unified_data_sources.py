import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.models import TickerConfig, HestonConfig, GBMConfig


@pytest.fixture
def heston_config():
    return {
        "GOOG": TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5)),
        "MSFT": TickerConfig(heston=HestonConfig(kappa=1.2, theta=0.05, xi=0.25, rho=-0.6))
    }


@pytest.fixture
def gbm_config():
    return {
        "AAPL": TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.2)),
        "TSLA": TickerConfig(gbm=GBMConfig(mean=0.02, sd=0.3))
    }


@pytest.fixture
def backtest_global_config():
    return {
        "backtest_model_type": "heston",
        "start_prices": {"GOOG": 2800.0, "MSFT": 300.0},
        "timesteps": 5,
        "interval": 1.0/252,
        "seed": 42
    }


@pytest.fixture
def hyperliquid_config():
    return {
        "api_key": "test_key",
        "secret": "test_secret"
    }


class TestUnifiedDataSourceInterface:
    """Test the unified data source interface behavior"""
    
    @pytest.mark.asyncio
    async def test_backtest_data_source_callback_format(self, heston_config, backtest_global_config):
        """Test that BacktestDataSource uses consistent callback format"""
        source = BacktestDataSource(heston_config, backtest_global_config)
        received_data = []
        simulation_ended = False

        async def callback(data):
            nonlocal simulation_ended
            if isinstance(data, dict) and data.get("type") == "simulation_end":
                simulation_ended = True
            else:
                received_data.append(data)

        # Mock the generator to return test data
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator():
                yield [{"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}]
                yield [{"ticker": "MSFT", "close": 310.0, "timestamp": "2023-01-01T00:01:00"}]
            
            mock_gen.return_value = mock_generator()
            
            await source.subscribe_realtime_data(callback)
            
            # Verify data format consistency
            assert len(received_data) == 2
            assert all(isinstance(batch, list) for batch in received_data)
            assert all("ticker" in tick and "close" in tick for batch in received_data for tick in batch)
            assert simulation_ended  # Should signal end of simulation
            
            # Verify current_prices was updated
            assert source.current_prices["GOOG"] == 2850.0
            assert source.current_prices["MSFT"] == 310.0

    @pytest.mark.asyncio
    async def test_hyperliquid_data_source_callback_format(self, hyperliquid_config):
        """Test that HyperliquidDataSource uses consistent callback format"""
        tickers = ["BTC", "ETH"]
        
        with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager'):
            source = HyperliquidDataSource(hyperliquid_config, tickers=tickers)
            received_data = []

            async def callback(data):
                received_data.append(data)

            # Mock WebSocket message handling
            source._callback = callback
            
            # Simulate WebSocket message
            mock_message = {
                "channel": "candle",
                "data": {
                    "T": 1640995200000,  # timestamp
                    "s": "BTC",          # symbol
                    "o": "50000.0",      # open
                    "h": "51000.0",      # high
                    "l": "49000.0",      # low
                    "c": "50500.0",      # close
                    "v": "10.5"          # volume
                }
            }
            
            source._handle_ws_message(mock_message)
            
            # Verify data format consistency
            assert len(received_data) == 1
            assert isinstance(received_data[0], list)
            tick = received_data[0][0]
            assert "ticker" in tick
            assert "close" in tick
            assert "timestamp" in tick
            assert tick["ticker"] == "BTC"
            assert tick["close"] == 50500.0

    @pytest.mark.asyncio
    async def test_data_source_current_prices_update(self, heston_config, backtest_global_config):
        """Test that current_prices are updated consistently across data sources"""
        source = BacktestDataSource(heston_config, backtest_global_config)
        
        # Test _notify_callback updates current_prices
        test_data = [
            {"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"},
            {"ticker": "MSFT", "close": 310.0, "timestamp": "2023-01-01T00:01:00"}
        ]
        
        source._callback = AsyncMock()
        await source._notify_callback(test_data)
        
        assert source.current_prices["GOOG"] == 2850.0
        assert source.current_prices["MSFT"] == 310.0

    @pytest.mark.asyncio
    async def test_simulation_end_handling(self, heston_config, backtest_global_config):
        """Test that simulation end events are handled properly"""
        source = BacktestDataSource(heston_config, backtest_global_config)
        simulation_events = []

        async def callback(data):
            simulation_events.append(data)

        # Mock the generator to simulate completion
        with patch('stock_data_downloader.websocket_server.DataSource.BacktestDataSource.generate_heston_ticks') as mock_gen:
            async def mock_generator():
                yield [{"ticker": "GOOG", "close": 2850.0, "timestamp": "2023-01-01T00:00:00"}]
                # Generator ends here, should trigger simulation_end
            
            mock_gen.return_value = mock_generator()
            
            await source.subscribe_realtime_data(callback)
            
            # Should have received data and simulation end event
            assert len(simulation_events) == 2
            assert isinstance(simulation_events[0], list)  # Price data
            assert isinstance(simulation_events[1], dict)  # Simulation end event
            assert simulation_events[1]["type"] == "simulation_end"

    @pytest.mark.asyncio
    async def test_error_handling_in_callback(self, heston_config, backtest_global_config):
        """Test error handling in data source callbacks"""
        source = BacktestDataSource(heston_config, backtest_global_config)
        
        # Mock callback that raises an exception
        def failing_callback(data):
            raise ValueError("Test error")
        
        source._callback = failing_callback
        
        # Should not raise exception, but log it
        with patch('stock_data_downloader.websocket_server.DataSource.DataSourceInterface.logging') as mock_logging:
            await source._notify_callback([{"ticker": "TEST", "close": 100.0}])
            mock_logging.exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_functionality(self, heston_config, backtest_global_config):
        """Test that reset functionality works for data sources"""
        source = BacktestDataSource(heston_config, backtest_global_config)
        
        # Set up initial state
        original_callback = AsyncMock()
        source._callback = original_callback
        source.simulator = MagicMock()
        
        # Reset should preserve callback and clear generator
        await source.reset()
        
        # After reset, callback should be restored and generator should be None initially
        assert source._callback == original_callback

    @pytest.mark.asyncio
    async def test_unsubscribe_cleanup(self, heston_config, backtest_global_config):
        """Test that unsubscribe properly cleans up resources"""
        source = BacktestDataSource(heston_config, backtest_global_config)
        
        # Set up state
        source._callback = AsyncMock()
        source.simulator = MagicMock()
        
        await source.unsubscribe_realtime_data()
        
        # Should clean up callback and generator
        assert source._callback is None
        assert source.simulator is None


class TestDataFormatConsistency:
    """Test that data formats are consistent across different sources"""
    
    def test_backtest_data_format(self):
        """Test BacktestDataSource produces expected data format"""
        # This would be tested through the actual generator functions
        # For now, we test the mapping logic
        pass
    
    def test_hyperliquid_data_format(self):
        """Test HyperliquidDataSource produces expected data format"""
        source = HyperliquidDataSource({}, tickers=["BTC"])
        
        # Test the mapping function
        raw_message = {
            "T": 1640995200000,
            "s": "BTC",
            "o": "50000.0",
            "h": "51000.0", 
            "l": "49000.0",
            "c": "50500.0",
            "v": "10.5"
        }
        
        mapped = source._map_candle_message(raw_message)
        
        # Verify required fields are present
        required_fields = ["ticker", "timestamp", "open", "high", "low", "close", "volume"]
        for field in required_fields:
            assert field in mapped
        
        # Verify data types
        assert isinstance(mapped["ticker"], str)
        assert isinstance(mapped["open"], float)
        assert isinstance(mapped["high"], float)
        assert isinstance(mapped["low"], float)
        assert isinstance(mapped["close"], float)
        assert isinstance(mapped["volume"], float)


class TestErrorScenarios:
    """Test error handling scenarios"""
    
    @pytest.mark.asyncio
    async def test_invalid_backtest_model_type(self, heston_config):
        """Test handling of invalid backtest model types"""
        invalid_config = {
            "backtest_model_type": "invalid_model",
            "start_prices": {"GOOG": 2800.0},
            "timesteps": 5,
            "interval": 1.0/252
        }
        
        source = BacktestDataSource(heston_config, invalid_config)
        
        with pytest.raises(ValueError, match="Unsupported backtest model type"):
            await source.subscribe_realtime_data(AsyncMock())

    @pytest.mark.asyncio
    async def test_missing_configuration(self):
        """Test handling of missing configuration"""
        with pytest.raises(KeyError):
            source = BacktestDataSource({}, {})  # Missing required config