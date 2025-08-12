import pytest
from stock_data_downloader.websocket_server.factories.DataSourceFactory import DataSourceFactory
from stock_data_downloader.models import (
    BacktestDataSourceConfig,
    DataSourceConfig,
    HyperliquidDataSourceConfig,
    TickerConfig,
    GBMConfig,
)
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource

def test_create_backtest_data_source():
    backtest_cfg = BacktestDataSourceConfig(
        source_type="backtest",
        backtest_model_type="gbm",
        start_prices={"AAPL": 100.0},
        timesteps=5,
        interval=1/252,
        seed=42,
        ticker_configs={
            "AAPL": TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.1))
        },
    )

    ds_cfg = DataSourceConfig(source_type="backtest", config=backtest_cfg)
    ds = DataSourceFactory.create_data_source(ds_cfg)

    # Should return an instance of the concrete BacktestDataSource
    assert isinstance(ds, BacktestDataSource)

def test_create_hyperliquid_data_source_monkeypatched(monkeypatch):
    # Replace actual HyperliquidDataSource with a dummy so test is hermetic
    class DummyHL:
        def __init__(self, config, network, tickers, interval):
            self.config = config
            self.network = network
            self.tickers = tickers
            self.interval = interval

    monkeypatch.setattr(
        "stock_data_downloader.websocket_server.factories.DataSourceFactory.HyperliquidDataSource",
        DummyHL,
    )

    hyper_cfg = HyperliquidDataSourceConfig(
        source_type="hyperliquid",
        network="testnet",
        tickers=["BTC-USD"],
        interval="1m",
        api_config={"key": "value"},
    )

    ds_cfg = DataSourceConfig(source_type="hyperliquid", config=hyper_cfg)
    ds = DataSourceFactory.create_data_source(ds_cfg)

    assert isinstance(ds, DummyHL)
    assert ds.tickers == ["BTC-USD"]
    assert ds.network == "testnet"
    assert ds.interval == "1m"

def test_unsupported_type_raises():
    backtest_cfg = BacktestDataSourceConfig(
        source_type="backtest",
        backtest_model_type="gbm",
        start_prices={},
        timesteps=1,
        interval=1/252,
        ticker_configs={},
    )
    ds_cfg = DataSourceConfig(source_type="unsupported_type", config=backtest_cfg)
    with pytest.raises(ValueError):
        DataSourceFactory.create_data_source(ds_cfg)