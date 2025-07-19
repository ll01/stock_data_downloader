import asyncio
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import Dict, List, Any

from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.models import TickerConfig, HestonConfig


class TestHyperliquidCallbackAlignment:
    """Test that HyperliquidDataSource callback mechanism is aligned with BacktestDataSource"""
    
    def test_hyperliquid_callback_format_alignment(self):
        """Test that HyperliquidDataSource uses the same callback format as BacktestDataSource"""
        # Setup test data
        hyperliquid_config = {"api_key": "test_key", "secret": "test_secret"}
        tickers = ["BTC"]
        
        # Create data source
        with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager'):
            source = HyperliquidDataSource(hyperliquid_config, tickers=tickers)
            
            # Create a callback to capture data
            received_data = []
            
            def test_callback(data):
                received_data.append(data)
            
            # Set up the callback
            source._callback = test_callback
            
            # Simulate a WebSocket message
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
            
            # Process the message
            source._handle_ws_message(mock_message)
            
            # Verify the data format
            assert len(received_data) == 1
            assert isinstance(received_data[0], list)
            assert len(received_data[0]) == 1
            
            tick = received_data[0][0]
            assert "ticker" in tick
            assert "close" in tick
            assert "timestamp" in tick
            assert tick["ticker"] == "BTC"
            assert tick["close"] == 50500.0
    
    def test_hyperliquid_error_handling(self):
        """Test that HyperliquidDataSource handles errors properly"""
        hyperliquid_config = {"api_key": "test_key", "secret": "test_secret"}
        
        with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager'):
            source = HyperliquidDataSource(hyperliquid_config, tickers=["BTC"])
            
            # Instead of testing the logging directly, let's verify the exception handling works
            # by ensuring no exception is raised when processing fails
            source._map_candle_message = MagicMock(side_effect=ValueError("Invalid data"))
            
            # This should not raise an exception
            try:
                source._handle_ws_message({"channel": "candle", "data": {}})
                exception_caught = True
            except:
                exception_caught = False
                
            assert exception_caught, "Exception was not properly handled"
    
    @pytest.mark.asyncio
    async def test_connect_with_retry_logic(self):
        """Test that _connect_with_retry implements proper retry logic"""
        hyperliquid_config = {"api_key": "test_key", "secret": "test_secret"}
        
        with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager') as mock_ws_class:
            # Setup mock WebsocketManager to fail on first attempt
            mock_ws_instance = MagicMock()
            mock_ws_class.return_value = mock_ws_instance
            mock_ws_instance.start.side_effect = [Exception("Connection error"), None]
            
            source = HyperliquidDataSource(hyperliquid_config, tickers=["BTC"])
            
            # Mock sleep to speed up test
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                await source._connect_with_retry()
                
                # Verify retry logic
                assert mock_ws_instance.start.call_count == 2
                assert mock_sleep.call_count == 1
                
    @pytest.mark.asyncio
    async def test_subscribe_realtime_data_with_error_handling(self):
        """Test that subscribe_realtime_data handles subscription errors properly"""
        hyperliquid_config = {"api_key": "test_key", "secret": "test_secret"}
        tickers = ["BTC", "ETH"]
        
        with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.WebsocketManager') as mock_ws_class:
            mock_ws_instance = MagicMock()
            mock_ws_class.return_value = mock_ws_instance
            
            # Mock _connect_with_retry to avoid actual connection
            with patch.object(HyperliquidDataSource, '_connect_with_retry', new_callable=AsyncMock) as mock_connect:
                source = HyperliquidDataSource(hyperliquid_config, tickers=tickers)
                
                # Make subscribe fail for the second ticker
                mock_ws_instance.subscribe.side_effect = [123, Exception("Subscription error")]
                
                with patch('stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource.logger') as mock_logger:
                    await source.subscribe_realtime_data(AsyncMock())
                    
                    # Verify error handling
                    assert len(source._subscriptions) == 1
                    assert mock_logger.error.call_count == 1
                    assert mock_logger.info.call_count >= 1