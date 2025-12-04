import pytest
import asyncio
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.models import BacktestDataSourceConfig, TickerConfig, BackTestMode, GBMConfig

@pytest.mark.asyncio
async def test_delisting_logic():
    # Setup config with delisted asset
    config = BacktestDataSourceConfig(
        source_type="backtest",
        backtest_model_type="gbm",
        start_prices={"AAPL": 100.0, "DELISTED": 50.0},
        timesteps=10,
        interval=1.0,
        ticker_configs={
            "AAPL": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01)),
            "DELISTED": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01))
        },
        delisted_assets={"DELISTED": 5}, # Delists after step 5
        backtest_mode=BackTestMode.PULL
    )
    
    ds = BacktestDataSource(backtest_config=config)
    
    # Step 1-5: Should see both assets
    for i in range(5):
        response = await ds.get_next_bar_for_client("test_client")
        assert response.error_message is None
        tickers = [t.ticker for t in response.data]
        assert "AAPL" in tickers
        assert "DELISTED" in tickers
        
    # Step 6+: Should only see AAPL
    for i in range(5):
        response = await ds.get_next_bar_for_client("test_client")
        assert response.error_message is None
        tickers = [t.ticker for t in response.data]
        assert "AAPL" in tickers
        assert "DELISTED" not in tickers

@pytest.mark.asyncio
async def test_delisting_stream_logic():
    # Setup config with delisted asset
    config = BacktestDataSourceConfig(
        source_type="backtest",
        backtest_model_type="gbm",
        start_prices={"AAPL": 100.0, "DELISTED": 50.0},
        timesteps=10,
        interval=1.0,
        ticker_configs={
            "AAPL": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01)),
            "DELISTED": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01))
        },
        delisted_assets={"DELISTED": 3}, # Delists after step 3
        backtest_mode=BackTestMode.PUSH
    )
    
    ds = BacktestDataSource(backtest_config=config)
    
    received_batches = []
    
    async def callback(msg_type, data):
        if msg_type == "price_update":
            received_batches.append(data)
            
    await ds.subscribe_realtime_data(callback)
    
    # Wait for simulation to finish (it's async but fast)
    await asyncio.sleep(1)
    
    # Should get 11 batches (initial + 10 timesteps)
    assert len(received_batches) == 11
    
    # Check first 4 batches (initial + first 3 timesteps)
    for i in range(4):
        tickers = [t.ticker for t in received_batches[i]]
        assert "AAPL" in tickers
        assert "DELISTED" in tickers
        
    # Check remaining batches (after delisting)
    for i in range(4, 11):
        tickers = [t.ticker for t in received_batches[i]]
        assert "AAPL" in tickers
        assert "DELISTED" not in tickers

@pytest.mark.asyncio
async def test_randomize_universe():
    # Setup config with multiple tickers and randomize_universe enabled
    config = BacktestDataSourceConfig(
        source_type="backtest",
        backtest_model_type="gbm",
        start_prices={"AAPL": 100.0, "GOOGL": 200.0, "MSFT": 300.0, "TSLA": 400.0},
        timesteps=10,
        interval=1.0,
        randomize_universe=True,
        randomize_universe_size=2,  # Select 2 out of 4 tickers
        seed=42,  # Fixed seed for reproducibility
        ticker_configs={
            "AAPL": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01)),
            "GOOGL": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01)),
            "MSFT": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01)),
            "TSLA": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01))
        },
        backtest_mode=BackTestMode.PULL
    )

    ds = BacktestDataSource(backtest_config=config)

    # Record initial selection
    initial_tickers = set(ds.tickers)
    assert len(initial_tickers) == 2

    # Reset and check that tickers change
    await ds.reset()
    reset_tickers = set(ds.tickers)
    assert len(reset_tickers) == 2

    # Since we use a counter, the selection should be different on reset
    # With seed 42 + 0 = 42, then 42 + 1 = 43, different selections
    assert initial_tickers != reset_tickers

if __name__ == "__main__":
    # Manually run async tests if executed as script
    async def run_tests():
        await test_delisting_logic()
        await test_delisting_stream_logic()
        await test_randomize_universe()
        print("All tests passed!")

    asyncio.run(run_tests())
