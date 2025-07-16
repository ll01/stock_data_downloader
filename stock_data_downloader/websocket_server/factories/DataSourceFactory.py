import logging
from stock_data_downloader.models import TickerConfig
from stock_data_downloader.websocket_server.DataSource.BrownianMotionDataSource import BrownianMotionDataSource
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource



from typing import Any, Dict

logger = logging.getLogger(__name__)

class DataSourceFactory:
    """Factory class for creating data source instances based on configuration"""

    @staticmethod
    def create_data_source(config: Dict[str, Any]) -> DataSourceInterface:
        """
        Create a data source instance based on the provided configuration

        Args:
            config: Dictionary with data source configuration

        Returns:
            DataSourceInterface implementation

        Raises:
            ValueError: If the data source type is not supported
        """
       
        source_name = config.get("name")
        
        if not source_name:
            logger.error("Data source name is required in the configuration.")
            raise ValueError("Data source name is required in the configuration.")
        if source_name == "backtest":
            logger.info("Creating BacktestDataSource")
            
            ticker_configs_raw: Dict[str, Dict[str, Any]] = config.get("ticker_configs", {})
            ticker_configs = {
                ticker: TickerConfig(**config) for ticker, config in ticker_configs_raw.items()
            }

            # Create and return BacktestDataSource
            return BacktestDataSource(
                ticker_configs=ticker_configs,
                global_config=config
            )
        elif source_name == "hyperliquid":
            logger.info("Creating HyperliquidDataSource")

            # Extract HyperliquidDataSource specific settings
            api_config = config.get("api_config", {})
            network = config.get("network", "mainnet")
            tickers = config.get("tickers", [])

            # Create and return HyperliquidDataSource
            return HyperliquidDataSource(
                config=api_config,
                network=network,
                tickers=tickers
            )
        

        else:
            available_types = ["backtest", "hyperliquid"]
            err_msg = f"Data source type '{source_name}' not supported. Available types: {', '.join(available_types)}"
            logger.error(err_msg)
            raise ValueError(err_msg)