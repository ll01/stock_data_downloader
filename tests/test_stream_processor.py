import asyncio
import pytest
from datetime import datetime, timezone
from stock_data_downloader.websocket_server.stream_processor import StreamProcessor

class TestStreamProcessor:
    """Tests for the enhanced StreamProcessor class"""

    @pytest.mark.asyncio
    async def test_field_normalization(self):
        """Test that the processor correctly normalizes different field names"""
        processor = StreamProcessor()
        await processor.start()

        # Test data with different field naming conventions
        test_data = [
            # Hyperliquid style data
            {
                "s": "BTC",  # symbol/ticker
                "t": 1746192900000,  # timestamp in ms
                "o": "96899.0",
                "h": "96899.5",
                "l": "96898.5",
                "c": "96899.0",  # close/price
                "v": "0.01",
                "source": "hyperliquid",
                "network": "mainnet"
            },
            # Backtest style data
            {
                "ticker": "ETH",
                "timestamp": "2025-07-01T12:15:59.999000+00:00",
                "close": 3500.25,
                "open": 3499.75,
                "high": 3501.00,
                "low": 3498.50,
                "volume": 10.5,
                "source": "backtest"
            },
            # Another format
            {
                "symbol": "SOL",
                "close": 150.75,
                "time": 1746192800,  # timestamp in seconds
                "exchange": "binance"
            }
        ]

        received_data = []
        
        # Create a test subscriber
        async def test_subscriber(data):
            received_data.extend(data)
        
        processor.subscribe(test_subscriber)
        
        # Process the test data
        await processor.ingest(test_data)
        
        # Give time for processing to complete
        await asyncio.sleep(0.1)
        
        # Stop the processor
        await processor.stop()
        
        # Verify the results
        assert len(received_data) == 3
        
        # Check BTC data normalization
        btc_data = next(item for item in received_data if item["ticker"] == "BTC")
        assert btc_data["close"] == 96899.0
        assert btc_data["open"] == 96899.0
        assert btc_data["high"] == 96899.5
        assert btc_data["low"] == 96898.5
        assert btc_data["volume"] == 0.01
        assert btc_data["source"] == "hyperliquid"
        assert btc_data["network"] == "mainnet"
        
        # Check ETH data normalization
        eth_data = next(item for item in received_data if item["ticker"] == "ETH")
        assert eth_data["close"] == 3500.25
        assert eth_data["open"] == 3499.75
        assert eth_data["high"] == 3501.00
        assert eth_data["low"] == 3498.50
        assert eth_data["volume"] == 10.5
        assert eth_data["source"] == "backtest"
        
        # Check SOL data normalization
        sol_data = next(item for item in received_data if item["ticker"] == "SOL")
        assert sol_data["close"] == 150.75
        assert sol_data["source"] == "binance"
        # Verify timestamp conversion
        assert "timestamp" in sol_data

    @pytest.mark.asyncio
    async def test_historical_cache(self):
        """Test that the processor correctly maintains historical cache"""
        processor = StreamProcessor(max_cache_size=5)
        await processor.start()
        
        # Generate test data for a single ticker
        test_data = []
        for i in range(10):
            test_data.append({
                "ticker": "BTC",
                "timestamp": f"2025-07-01T12:{i:02d}:00.000000+00:00",
                "close": 96900.0 + i,
                "source": "test"
            })
        
        # Process the test data
        for tick in test_data:
            await processor.ingest(tick)
            await asyncio.sleep(0.01)  # Small delay to ensure processing
        
        # Stop the processor
        await processor.stop()
        
        # Verify the historical cache
        btc_history = processor.get_historical_data("BTC")
        
        # Should only have the last 5 items due to max_cache_size
        assert len(btc_history) == 5
        
        # Verify the items are the most recent ones
        assert btc_history[0]["close"] == 96905.0
        assert btc_history[-1]["close"] == 96909.0

    @pytest.mark.asyncio
    async def test_statistics_tracking(self):
        """Test that the processor correctly tracks statistics"""
        processor = StreamProcessor()
        await processor.start()
        
        # Process some valid and invalid data
        valid_data = [
            {"ticker": "BTC", "close": 96900.0, "timestamp": "2025-07-01T12:00:00.000000+00:00", "source": "test"},
            {"ticker": "ETH", "close": 3500.0, "timestamp": "2025-07-01T12:00:00.000000+00:00", "source": "test"}
        ]
        
        invalid_data = [
            {"ticker": "SOL"},  # Missing price and timestamp
            "not a dict"  # Not a dictionary
        ]
        
        await processor.ingest(valid_data)
        await processor.ingest(invalid_data)
        
        # Give time for processing to complete
        await asyncio.sleep(0.1)
        
        # Stop the processor
        await processor.stop()
        
        # Verify statistics
        stats = processor.get_stats()
        assert stats["processed_ticks"] == 2
        assert stats["invalid_ticks"] == 2
        assert set(stats["sources"]) == {"test"}
        assert stats["ticker_count"] == 2
        assert stats["subscriber_count"] == 0
        assert stats["uptime"] > 0
        assert stats["avg_processing_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_simulation_end_handling(self):
        """Test that the processor correctly handles simulation end events"""
        processor = StreamProcessor()
        await processor.start()
        
        simulation_end_received = False
        
        async def test_subscriber(data):
            nonlocal simulation_end_received
            if isinstance(data, dict) and data.get("type") == "simulation_end":
                simulation_end_received = True
        
        processor.subscribe(test_subscriber)
        
        # Send a simulation end event
        await processor.ingest({"type": "simulation_end"})
        
        # Give time for processing to complete
        await asyncio.sleep(0.1)
        
        # Stop the processor
        await processor.stop()
        
        # Verify that the simulation end event was received
        assert simulation_end_received is True

    @pytest.mark.asyncio
    async def test_timestamp_normalization(self):
        """Test that the processor correctly normalizes different timestamp formats"""
        processor = StreamProcessor()
        await processor.start()
        
        # Test data with different timestamp formats
        test_data = [
            # Unix timestamp in milliseconds
            {
                "ticker": "BTC",
                "close": 96900.0,
                "t": 1746192900000,
                "source": "test1"
            },
            # Unix timestamp in seconds
            {
                "ticker": "ETH",
                "close": 3500.0,
                "time": 1746192900,
                "source": "test2"
            },
            # ISO format string
            {
                "ticker": "SOL",
                "close": 150.0,
                "timestamp": "2025-07-01T12:00:00.000000+00:00",
                "source": "test3"
            }
        ]
        
        received_data = []
        
        async def test_subscriber(data):
            received_data.extend(data)
        
        processor.subscribe(test_subscriber)
        
        # Process the test data
        await processor.ingest(test_data)
        
        # Give time for processing to complete
        await asyncio.sleep(0.1)
        
        # Stop the processor
        await processor.stop()
        
        # Verify that all timestamps were normalized
        for item in received_data:
            assert "timestamp" in item
            # Verify it's a string (ISO format)
            assert isinstance(item["timestamp"], str)