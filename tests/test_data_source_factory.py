import pytest
from unittest.mock import patch, MagicMock
from stock_data_downloader.models import (
    DataSourceConfig,
    BacktestDataSourceConfig,
    HyperliquidDataSourceConfig,
    TickerConfig,
    HestonConfig,
    GBMConfig
)
from stock_data_downloader.websocket_server.factories.DataSourceFactory import DataSourceFactory
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource


class TestDataSourceFactory:
    """Test the DataSourceFactory class"""

    def test_create_backtest_data_source_heston(self):
        """Test creating a BacktestDataSource with Heston model"""
        # Create test config
        ticker_configs = {
            "AAPL": TickerConfig(
                heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5)
            )
        }
        backtest_config = BacktestDataSourceConfig(
            source_type="backtest",
            backtest_model_type="heston",
            start_prices={"AAPL": 150.0},
            timesteps=100,
            interval=1.0/252,
            seed=42,
            ticker_configs=ticker_configs
        )
        config = DataSourceConfig(
            source_type="backtest",
            config=backtest_config
        )

        # Create data source
        with patch('stock_data_downloader.websocket_server.factories.DataSourceFactory.logger') as mock_logger:
            data_source = DataSourceFactory.create_data_source(config)

            # Verify logger was called with correct message
            mock_logger.info.assert_any_call("Creating data source with type: backtest")
            mock_logger.info.assert_any_call("Creating BacktestDataSource with heston model")

        # Verify data source type and configuration
        assert isinstance(data_source, BacktestDataSource)
        assert data_source.tickers == ["AAPL"]
        assert data_source.backtest_config.backtest_model_type == "heston"
        assert data_source.backtest_config.start_prices == {"AAPL": 150.0}
        assert data_source.backtest_config.timesteps == 100
        assert data_source.backtest_config.interval == 1.0/252
        assert data_source.backtest_config.seed == 42

    def test_create_backtest_data_source_gbm(self):
        """Test creating a BacktestDataSource with GBM model"""
        # Create test config
        ticker_configs = {
            "TSLA": TickerConfig(
                gbm=GBMConfig(mean=0.01, sd=0.2)
            )
        }
        backtest_config = BacktestDataSourceConfig(
            source_type="backtest",
            backtest_model_type="gbm",
            start_prices={"TSLA": 200.0},
            timesteps=50,
            interval=1.0/252,
            seed=123,
            ticker_configs=ticker_configs
        )
        config = DataSourceConfig(
            source_type="backtest",
            config=backtest_config
        )

        # Create data source
        data_source = DataSourceFactory.create_data_source(config)

        # Verify data source type and configuration
        assert isinstance(data_source, BacktestDataSource)
        assert data_source.tickers == ["TSLA"]
        assert data_source.backtest_config.backtest_model_type == "gbm"
        assert data_source.backtest_config.start_prices == {"TSLA": 200.0}
        assert data_source.backtest_config.timesteps == 50
        assert data_source.backtest_config.interval == 1.0/252
        assert data_source.backtest_config.seed == 123

    def test_create_hyperliquid_data_source(self):
        """Test creating a HyperliquidDataSource"""
        # Create test config
        hyperliquid_config = HyperliquidDataSourceConfig(
            source_type="hyperliquid",
            network="mainnet",
            tickers=["BTC", "ETH"],
            interval="1m",
            api_config={"api_key": "test_key"}
        )
        config = DataSourceConfig(
            source_type="hyperliquid",
            config=hyperliquid_config
        )

        # Mock HyperliquidDataSource to avoid actual API calls
        with patch('stock_data_downloader.websocket_server.factories.DataSourceFactory.HyperliquidDataSource') as mock_hyperliquid:
            mock_instance = MagicMock()
            mock_hyperliquid.return_value = mock_instance
            
            # Create data source
            data_source = DataSourceFactory.create_data_source(config)
            
            # Verify HyperliquidDataSource was created with correct parameters
            mock_hyperliquid.assert_called_once_with(
                config={"api_key": "test_key"},
                network="mainnet",
                tickers=["BTC", "ETH"],
                interval="1m"
            )
            
            assert data_source == mock_instance

    def test_invalid_data_source_type(self):
        """Test creating a data source with an invalid type"""
        # Create test config with invalid source type
        config = DataSourceConfig(
            source_type="invalid_type",
            config=BacktestDataSourceConfig(
                source_type="backtest",
                backtest_model_type="gbm",
                start_prices={},
                timesteps=1,
                interval=1.0,
                ticker_configs={}
            )  # Minimal valid config to satisfy Pydantic
        )

        # Attempt to create data source
        with pytest.raises(ValueError) as excinfo:
            DataSourceFactory.create_data_source(config)
        
        # Verify error message
        assert "Data source type 'invalid_type' not supported" in str(excinfo.value)
        assert "Available types: backtest, hyperliquid" in str(excinfo.value)

    def test_invalid_backtest_config_type(self):
        """Test creating a backtest data source with invalid config type"""
        # Create test config with wrong config type
        config = DataSourceConfig(
            source_type="backtest",
            config=HyperliquidDataSourceConfig(  # Wrong config type
                source_type="hyperliquid",
                network="mainnet",
                tickers=["BTC"]
            )
        )

        # Attempt to create data source
        with pytest.raises(ValueError) as excinfo:
            DataSourceFactory.create_data_source(config)
        
        # Verify error message
        assert "Expected BacktestDataSourceConfig for backtest data source" in str(excinfo.value)

    def test_invalid_hyperliquid_config_type(self):
        """Test creating a hyperliquid data source with invalid config type"""
        # Create test config with wrong config type
        ticker_configs = {"AAPL": TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.2))}
        config = DataSourceConfig(
            source_type="hyperliquid",
            config=BacktestDataSourceConfig(  # Wrong config type
                source_type="backtest",
                backtest_model_type="gbm",
                start_prices={"AAPL": 150.0},
                timesteps=100,
                interval=1.0/252,
                ticker_configs=ticker_configs
            )
        )

        # Attempt to create data source
        with pytest.raises(ValueError) as excinfo:
            DataSourceFactory.create_data_source(config)
        
        # Verify error message
        assert "Expected HyperliquidDataSourceConfig for Hyperliquid data source" in str(excinfo.value)