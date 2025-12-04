import asyncio
import pytest
from typing import Dict, List, Any
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.models import TickerConfig, HestonConfig, GBMConfig

@pytest.fixture
def backtest_config():
    return {
        "ticker_configs": {
            "GOOG": TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5)),
            "MSFT": TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.2))
        },
        "global_config": {
            "model_type": "heston",
            "start_prices": {"GOOG": 2800.0, "MSFT": 300.0},
            "timesteps": 10,
            "interval": 1.0/252,
            "seed": 42
        }
    }

@pytest.mark.asyncio
async def test_backtest_data_source_subscription(backtest_config):
    # Create proper BacktestDataSourceConfig
    from stock_data_downloader.models import BacktestDataSourceConfig
    config = BacktestDataSourceConfig(
        source_type="backtest",
        backtest_model_type=backtest_config['global_config']['model_type'],
        start_prices=backtest_config['global_config']['start_prices'],
        timesteps=backtest_config['global_config']['timesteps'],
        interval=backtest_config['global_config']['interval'],
        seed=backtest_config['global_config']['seed'],
        ticker_configs={
            'GOOG': TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5)),
            'MSFT': TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.2))
        }
    )
    source = BacktestDataSource(backtest_config=config)
    received_data = []

    async def callback(event_type, data):
        received_data.append(data)

    # Run subscription in a task to avoid blocking
    subscription_task = asyncio.create_task(source.subscribe_realtime_data(callback))
    
    # Wait for data to arrive (with a timeout of 2 seconds)
    for _ in range(20):
        if len(received_data) > 0:
            break
        await asyncio.sleep(0.1)
    else:
        assert False, "No data received within 2 seconds"
    await source.unsubscribe_realtime_data()
    subscription_task.cancel()  # Cancel the task

    assert len(received_data) > 0
    assert "ticker" in received_data[0][0]
    assert "close" in received_data[0][0]