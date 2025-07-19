import os
import yaml
import logging
from typing import Dict, Any
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
    TestExchangeConfig,
    HyperliquidExchangeConfig,
    CCXTExchangeConfig,
)

logger = logging.getLogger(__name__)


class ConfigFactory:
    """Factory for creating configuration objects from YAML files"""

    @staticmethod
    def load_config(config_path: str) -> AppConfig:
        """
        Load configuration from a YAML file

        Args:
            config_path: Path to the YAML configuration file

        Returns:
            AppConfig object with the loaded configuration
        """
        try:
            with open(config_path, "r") as f:
                raw_config = yaml.safe_load(f)

            return ConfigFactory.create_app_config(raw_config)
        except Exception as e:
            logger.error(f"Error loading configuration from {config_path}: {e}")
            raise

    @staticmethod
    def create_app_config(raw_config: Dict[str, Any]) -> AppConfig:
        """
        Create an AppConfig object from a raw configuration dictionary

        Args:
            raw_config: Raw configuration dictionary

        Returns:
            AppConfig object
        """
        # Extract data source configuration
        data_source_config = ConfigFactory._create_data_source_config(
            raw_config.get("data_source", {})
        )

        # Extract server configuration
        server_config = ConfigFactory._create_server_config(
            raw_config.get("server", {})
        )
        
        exchange_config = ConfigFactory._create_exchange_config(raw_config.get("exchange", {}))
        # Create AppConfig
        return AppConfig(
            data_source=data_source_config,
            server=server_config,
            initial_cash=raw_config.get("initial_cash", 100000.0),
            exchange=exchange_config
        )

    @staticmethod
    def _create_server_config(raw_config: Dict[str, Any]) -> ServerConfig:
        """
        Create a ServerConfig object from a raw configuration dictionary

        Args:
            raw_config: Raw configuration dictionary

        Returns:
            ServerConfig object
        """
        config = ServerConfig(
            data_downloader=UriConfig(
                host=raw_config.get("data_downloader", {}).get("host", "0.0.0.0"),
                port=raw_config.get("data_downloader", {}).get("port", 8000),
            ),
            broker=UriConfig(
                host=raw_config.get("broker", {}).get("host", "0.0.0.0"),
                port=raw_config.get("broker", {}).get("port", 8001),
            ),
            ping_interval=raw_config.get("ping_interval", 20),
            ping_timeout=raw_config.get("ping_timeout", 20),
        )
        broker_host = os.getenv("BROKER_HOST")
        broker_port = os.getenv("BROKER_PORT")
        data_downloader_host = os.getenv("DATA_DOWNLOADER_HOST")
        data_downloader_port = os.getenv("DATA_DOWNLOADER_PORT")
        if broker_host:
            config.broker.host = broker_host
        if broker_port:
            config.broker.port = int(broker_port)
        if data_downloader_host:
            config.data_downloader.host = data_downloader_host
        if data_downloader_port:
            config.data_downloader.port = int(data_downloader_port)
        return config

    @staticmethod
    def _create_data_source_config(raw_config: Dict[str, Any]) -> DataSourceConfig:
        """
        Create a DataSourceConfig object from a raw configuration dictionary

        Args:
            raw_config: Raw configuration dictionary

        Returns:
            DataSourceConfig object
        """
        source_type = raw_config.get("source_type", "backtest")

        if source_type == "backtest":
            # Create BacktestDataSourceConfig
            ticker_configs = {}
            for ticker, params in raw_config.get("ticker_configs", {}).items():
                if raw_config.get("backtest_model_type") == "heston":
                    # Extract the nested heston configuration
                    heston_params = params.get("heston", {})
                    ticker_configs[ticker] = TickerConfig(heston=HestonConfig(**heston_params))
                elif raw_config.get("backtest_model_type") == "gbm":
                    # Extract the nested gbm configuration
                    gbm_params = params.get("gbm", {})
                    ticker_configs[ticker] = TickerConfig(gbm=GBMConfig(**gbm_params))

            config = BacktestDataSourceConfig(
                source_type="backtest",
                backtest_model_type=raw_config.get("backtest_model_type", "heston"),
                start_prices=raw_config.get("start_prices", {}),
                timesteps=raw_config.get("timesteps", 252),
                interval=raw_config.get("interval", 1.0 / 252),
                seed=raw_config.get("seed"),
                ticker_configs=ticker_configs,
            )
        elif source_type == "hyperliquid":
            # Create HyperliquidDataSourceConfig
            config = HyperliquidDataSourceConfig(
                source_type="hyperliquid",
                network=raw_config.get("network", "mainnet"),
                tickers=raw_config.get("tickers", []),
                interval=raw_config.get("interval", "1m"),
                api_config=raw_config.get("api_config", {}),
            )
        else:
            available_types = ["backtest", "hyperliquid"]
            raise ValueError(
                f"Unsupported data source type: {source_type}. Available types: {', '.join(available_types)}"
            )

        return DataSourceConfig(source_type=source_type, config=config)

    @staticmethod
    def _create_exchange_config(raw_config: Dict[str, Any]) -> ExchangeConfig:
        """
        Create an ExchangeConfig object from a raw configuration dictionary

        Args:
            raw_config: Raw configuration dictionary for the exchange

        Returns:
            ExchangeConfig object
        """
        exchange_type = raw_config.get("type")
        if not exchange_type:
            raise ValueError("Exchange configuration must specify a 'type'")

        if exchange_type == "test":
            config = TestExchangeConfig(type="test")
        elif exchange_type == "hyperliquid":
            config = HyperliquidExchangeConfig(
                type="hyperliquid",
                network=raw_config.get("network", "mainnet"),
                api_config=raw_config.get("api_config", {})
            )
        elif exchange_type == "ccxt":
            exchange_id = raw_config.get("exchange_id")
            if not exchange_id:
                raise ValueError("CCXT exchange configuration must specify 'exchange_id'")
                
            config = CCXTExchangeConfig(
                type="ccxt",
                exchange_id=exchange_id,
                sandbox=raw_config.get("sandbox", False),
                credentials=raw_config.get("credentials", {}),
                options=raw_config.get("options", {}),
                api_config=raw_config.get("api_config", {})
            )
        else:
            available_types = ["test", "hyperliquid", "ccxt"]
            raise ValueError(
                f"Unsupported exchange type: {exchange_type}. Available types: {', '.join(available_types)}"
            )

        return ExchangeConfig(exchange=config)
