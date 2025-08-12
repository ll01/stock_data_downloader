import pytest
import asyncio
from unittest.mock import patch, MagicMock, mock_open
import argparse
from stock_data_downloader.run_server import (
    parse_arguments,
    is_valid_file_path,
    generate_basic_start_prices,
    main
)
from stock_data_downloader.models import (
    AppConfig,
    DataSourceConfig,
    BacktestDataSourceConfig,
    HyperliquidDataSourceConfig,
    ServerConfig,
    TickerConfig,
    HestonConfig,
    GBMConfig,
    UriConfig,
    ExchangeConfig,
    TestExchangeConfig
)
from stock_data_downloader.data_processing.TickerStats import TickerStats


class TestRunServer:
    """Test the run_server module"""

    def test_parse_arguments(self):
        """Test argument parsing"""
        with patch('argparse.ArgumentParser.parse_args',
                  return_value=argparse.Namespace(
                      config='config.yaml',
                      log_level='INFO',
                      sim_data_file='stats.parquet',
                      start_price=150.0
                  )):
            args = parse_arguments()
            assert args.config == 'config.yaml'
            assert args.log_level == 'INFO'
            assert args.sim_data_file == 'stats.parquet'
            assert args.start_price == 150.0

    def test_is_valid_file_path(self):
        """Test file path validation"""
        assert is_valid_file_path('valid_path.txt') is True
        assert is_valid_file_path('') is False
        assert is_valid_file_path('None') is False
        assert is_valid_file_path('none') is False
        assert is_valid_file_path('  ') is False

    def test_generate_basic_start_prices(self):
        """Test generating basic start prices"""
        tickers = {'AAPL': {}, 'MSFT': {}, 'GOOG': {}}
        start_prices = generate_basic_start_prices(100.0, tickers)
        assert start_prices == {'AAPL': 100.0, 'MSFT': 100.0, 'GOOG': 100.0}

    @pytest.mark.asyncio
    async def test_main_with_config_only(self):
        """Test main function with only config file"""
        # Mock command line arguments
        with patch('stock_data_downloader.run_server.parse_arguments',
                  return_value=argparse.Namespace(
                      config='config.yaml',
                      log_level='INFO',
                      sim_data_file=None,
                      start_price=100.0
                  )):
            
            # Mock setup_logging
            with patch('stock_data_downloader.run_server.setup_logging'):
                
                # Mock ConfigFactory.load_config
                mock_config = AppConfig(
                    data_source=DataSourceConfig(
                        source_type="hyperliquid",
                        config=HyperliquidDataSourceConfig(
                            source_type="hyperliquid",
                            network="mainnet",
                            tickers=["BTC"],
                            interval="1m",
                            api_config={"api_key": "test"}
                        )
                    ),
                    server=ServerConfig(data_downloader=UriConfig(host="localhost", port=8000)),
                    exchange=ExchangeConfig(exchange=TestExchangeConfig(type="test")),
                    initial_cash=100000.0
                )
                
                with patch('stock_data_downloader.run_server.ConfigFactory.load_config',
                          return_value=mock_config):
                    
                    # Mock start_server_from_config
                    with patch('stock_data_downloader.run_server.start_server_from_config') as mock_start_server:
                        
                        # Run main
                        result = await main()
                        
                        # Verify server was started with the config
                        mock_start_server.assert_called_once_with(mock_config)
                        assert result == 0

    @pytest.mark.asyncio
    async def test_main_with_sim_data_file(self):
        """Test main function with simulation data file"""
        # Mock command line arguments
        with patch('stock_data_downloader.run_server.parse_arguments',
                  return_value=argparse.Namespace(
                      config='config.yaml',
                      log_level='INFO',
                      sim_data_file='stats.parquet',
                      start_price=150.0
                  )):
            
            # Mock setup_logging
            with patch('stock_data_downloader.run_server.setup_logging'):
                
                # Create mock ticker stats
                mock_stats = {
                    'AAPL': TickerStats(mean=0.01, sd=0.2, kappa=1.0, theta=0.04, xi=0.2, rho=-0.5),
                    'MSFT': TickerStats(mean=0.015, sd=0.18, kappa=1.1, theta=0.05, xi=0.22, rho=-0.48)
                }
                
                # Mock load_stock_stats
                with patch('stock_data_downloader.run_server.load_stock_stats',
                          return_value=mock_stats):
                    
                    # Create mock config with backtest data source
                    ticker_configs = {
                        'AAPL': TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5)),
                        'MSFT': TickerConfig(heston=HestonConfig(kappa=1.1, theta=0.05, xi=0.22, rho=-0.48))
                    }
                    
                    mock_config = AppConfig(
                        data_source=DataSourceConfig(
                            source_type="backtest",
                            config=BacktestDataSourceConfig(
                                source_type="backtest",
                                backtest_model_type="heston",
                                start_prices={},  # Empty to test override
                                timesteps=100,
                                interval=1.0/252,
                                ticker_configs={}  # Empty to test override
                            )
                        ),
                        server=ServerConfig(data_downloader=UriConfig(host="localhost", port=8000)),
                        initial_cash=100000.0,
                        exchange=ExchangeConfig(exchange=TestExchangeConfig(type="test"))
                    )
                    
                    with patch('stock_data_downloader.run_server.ConfigFactory.load_config',
                              return_value=mock_config):
                        
                        # Mock start_server_from_config
                        with patch('stock_data_downloader.run_server.start_server_from_config') as mock_start_server:
                            
                            # Run main
                            result = await main()
                            
                            # Verify server was started with updated config
                            mock_start_server.assert_called_once()
                            
                            # Verify config was updated with stats data
                            config = mock_config.data_source.config
                            # Ensure we're working with backtest config
                            assert isinstance(config, BacktestDataSourceConfig)
                            assert len(config.ticker_configs) == 2
                            assert 'AAPL' in config.ticker_configs
                            assert 'MSFT' in config.ticker_configs
                            assert config.start_prices == {'AAPL': 150.0, 'MSFT': 150.0}
                            assert result == 0

    @pytest.mark.asyncio
    async def test_main_with_missing_start_prices(self):
        """Test main function with missing start prices"""
        # Mock command line arguments
        with patch('stock_data_downloader.run_server.parse_arguments',
                  return_value=argparse.Namespace(
                      config='config.yaml',
                      log_level='INFO',
                      sim_data_file=None,
                      start_price=120.0
                  )):
            
            # Mock setup_logging
            with patch('stock_data_downloader.run_server.setup_logging'):
                
                # Create ticker configs but no start prices
                ticker_configs = {
                    'GOOG': TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.2)),
                    'TSLA': TickerConfig(gbm=GBMConfig(mean=0.02, sd=0.3))
                }
                
                mock_config = AppConfig(
                    data_source=DataSourceConfig(
                        source_type="backtest",
                        config=BacktestDataSourceConfig(
                            source_type="backtest",
                            backtest_model_type="gbm",
                            start_prices={},  # Empty to test generation
                            timesteps=50,
                            interval=1.0/252,
                            ticker_configs=ticker_configs
                        )
                    ),
                    server=ServerConfig(data_downloader=UriConfig(host="localhost", port=8000)),
                    initial_cash=100000.0,
                    exchange=ExchangeConfig(exchange=TestExchangeConfig(type="test"))
                )
                
                with patch('stock_data_downloader.run_server.ConfigFactory.load_config',
                          return_value=mock_config):
                    
                    # Mock start_server_from_config
                    with patch('stock_data_downloader.run_server.start_server_from_config') as mock_start_server:
                        
                        # Run main
                        result = await main()
                        
                        # Verify server was started with updated config
                        mock_start_server.assert_called_once()
                        
                        # Verify start prices were generated
                        config = mock_config.data_source.config
                        # Ensure we're working with backtest config
                        assert isinstance(config, BacktestDataSourceConfig)
                        assert config.start_prices == {'GOOG': 120.0, 'TSLA': 120.0}
                        assert result == 0

    @pytest.mark.asyncio
    async def test_main_with_error(self):
        """Test main function with error"""
        # Mock command line arguments
        with patch('stock_data_downloader.run_server.parse_arguments',
                  return_value=argparse.Namespace(
                      config='config.yaml',
                      log_level='INFO',
                      sim_data_file=None,
                      start_price=100.0
                  )):
            
            # Mock setup_logging
            with patch('stock_data_downloader.run_server.setup_logging'):
                
                # Mock ConfigFactory.load_config to raise an exception
                with patch('stock_data_downloader.run_server.ConfigFactory.load_config',
                          side_effect=ValueError("Test error")):
                    
                    # Mock logging
                    with patch('stock_data_downloader.run_server.logging.error'):
                        
                        # Run main
                        result = await main()
                        
                        # Verify error result
                        assert result == 1