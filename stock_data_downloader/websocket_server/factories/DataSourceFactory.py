import logging
from typing import Dict, Any, Optional
from stock_data_downloader.models import (
    DataSourceConfig,
    BacktestDataSourceConfig,
    HyperliquidDataSourceConfig
)
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource

logger = logging.getLogger(__name__)

class DataSourceFactory:
    """Factory for creating data source instances"""
    
    @staticmethod
    def create_data_source(config: DataSourceConfig) -> DataSourceInterface:
        """
        Create a data source instance based on configuration
        
        Args:
            config: DataSourceConfig object
            
        Returns:
            DataSourceInterface instance
        """
        logger.info(f"Creating data source with type: {config.source_type}")
        source_type = config.source_type
        backtest_config = config.config
        if source_type == "backtest":
            if not isinstance(backtest_config, BacktestDataSourceConfig):
                raise ValueError("Expected BacktestDataSourceConfig for backtest data source")
                
            backtest_config = backtest_config
            
            logger.info(f"Creating BacktestDataSource with {backtest_config.backtest_model_type} model")
            logger.info(f"Ticker configs keys: {list(backtest_config.ticker_configs.keys())}")
            
            return BacktestDataSource(
                ticker_configs=backtest_config.ticker_configs,
                backtest_config=backtest_config
            )
            
        elif source_type == "hyperliquid":
            if not isinstance(backtest_config, HyperliquidDataSourceConfig):
                raise ValueError("Expected HyperliquidDataSourceConfig for Hyperliquid data source")
                
            hyperliquid_config = backtest_config
            
            logger.info(f"Creating HyperliquidDataSource for {len(hyperliquid_config.tickers)} tickers")
            
            return HyperliquidDataSource(
                config=hyperliquid_config.api_config,
                network=hyperliquid_config.network,
                tickers=hyperliquid_config.tickers,
                interval=hyperliquid_config.interval
            )
            
        else:
            available_types = ["backtest", "hyperliquid"]
            err_msg = f"Data source type '{source_type}' not supported. Available types: {', '.join(available_types)}"
            logger.error(err_msg)
            raise ValueError(err_msg)