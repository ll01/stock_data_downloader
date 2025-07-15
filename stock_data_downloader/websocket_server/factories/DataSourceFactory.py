import logging
from stock_data_downloader.websocket_server.DataSource.BrownianMotionDataSource import BrownianMotionDataSource
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource
from stock_data_downloader.websocket_server.DataSource.HestonModelDataSource import HestonModelDataSource



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
        source_type = config.get("type", "brownian").lower()

        if source_type == "brownian":
            logger.info("Creating BrownianMotionDataSource")

            # Extract BrownianMotionDataSource specific settings
            stats = config.get("stats", {})
            start_prices = config.get("start_prices", {})
            timesteps = config.get("timesteps", 252)
            interval = config.get("interval", 1.0)
            seed = config.get("seed")
            wait_time = config.get("wait_time", 0.1)

            # Create and return BrownianMotionDataSource
            return BrownianMotionDataSource(
                stats=stats,
                start_prices=start_prices,
                timesteps=timesteps,
                interval=interval,
                seed=seed,
                wait_time=wait_time
            )

        elif source_type == "hyperliquid":
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
        elif source_type == "heston":
            logger.info("Creating HestonModelDataSource")

            # Extract HestonModelDataSource specific settings
            stats = config.get("stats", {})
            start_prices = config.get("start_prices", {})
            timesteps = config.get("timesteps", 252)
            interval = config.get("interval", 1.0/252) # Default for daily steps
            seed = config.get("seed")
            wait_time = config.get("wait_time", 0.1)
            logger.debug(f"Creating HestonModelDataSource with stats: {stats}, start_prices: {start_prices}, timesteps: {timesteps}, interval: {interval}, seed: {seed}, wait_time: {wait_time}")
            logger.info(f"Creating HestonModelDataSource with stats: {stats}, start_prices: {start_prices}, timesteps: {timesteps}, interval: {interval}, seed: {seed}, wait_time: {wait_time}")
            # Create and return HestonModelDataSource
            return HestonModelDataSource(
                stats=stats,
                start_prices=start_prices,
                timesteps=timesteps,
                interval=interval,
                seed=seed,
                wait_time=wait_time
            )

        else:
            available_types = ["brownian", "hyperliquid", "heston"]
            err_msg = f"Data source type '{source_type}' not supported. Available types: {', '.join(available_types)}"
            logger.error(err_msg)
            raise ValueError(err_msg)