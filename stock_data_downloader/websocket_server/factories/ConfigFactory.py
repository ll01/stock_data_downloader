import os
import csv
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
        Load configuration from a YAML or JSON file

        Args:
            config_path: Path to the configuration file

        Returns:
            AppConfig object with the loaded configuration
        """
        try:
            with open(config_path, "r") as f:
                # Determine file type by extension
                if config_path.endswith('.json'):
                    import json
                    raw_config = json.load(f)
                else:
                    # Default to YAML for .yaml or .yml files
                    raw_config = yaml.safe_load(f)

            # Expand environment variables
            raw_config = ConfigFactory._expand_env_vars(raw_config)

            base_path = os.path.dirname(os.path.abspath(config_path))
            return ConfigFactory.create_app_config(raw_config, base_path)
        except Exception as e:
            logger.error(f"Error loading configuration from {config_path}: {e}")
            raise

    @staticmethod
    def _expand_env_vars(config: Any) -> Any:
        """
        Recursively expand environment variables in configuration values.
        Supports ${VAR} and $VAR syntax.
        """
        if isinstance(config, dict):
            return {k: ConfigFactory._expand_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [ConfigFactory._expand_env_vars(v) for v in config]
        elif isinstance(config, str):
            return os.path.expandvars(config)
        else:
            return config

    @staticmethod
    def create_app_config(raw_config: Dict[str, Any], base_path: str | None = None) -> AppConfig:
        """
        Create an AppConfig object from a raw configuration dictionary

        Args:
            raw_config: Raw configuration dictionary
            base_path: Directory containing the config file

        Returns:
            AppConfig object
        """
        # Extract data source configuration
        data_source_config = ConfigFactory._create_data_source_config(
            raw_config.get("data_source", {}),
            base_path,
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
    def _create_data_source_config(raw_config: Dict[str, Any], base_path: str | None) -> DataSourceConfig:
        """
        Create a DataSourceConfig object from a raw configuration dictionary

        Args:
            raw_config: Raw configuration dictionary
            base_path: Base directory used to resolve relative asset paths

        Returns:
            DataSourceConfig object
        """
        source_type = raw_config.get("source_type", "backtest")

        if source_type == "backtest":
            model_type = raw_config.get("backtest_model_type", "heston")
            ticker_configs = ConfigFactory._parse_inline_ticker_configs(
                raw_config.get("ticker_configs", {}),
                model_type,
            )
            csv_path = raw_config.get("ticker_params_csv")
            if csv_path:
                csv_configs = ConfigFactory._load_ticker_configs_from_csv(
                    csv_path,
                    model_type,
                    base_path,
                )
                ticker_configs.update(csv_configs)

            config = BacktestDataSourceConfig(
                source_type="backtest",
                backtest_model_type=model_type,
                start_prices=raw_config.get("start_prices", {}),
                timesteps=raw_config.get("timesteps", 252),
                interval=raw_config.get("interval", 1.0 / 252),
                seed=raw_config.get("seed"),
                ticker_configs=ticker_configs,
                history_steps=raw_config.get("history_steps"),
                backtest_mode=raw_config.get("backtest_mode"),
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
    def _parse_inline_ticker_configs(raw_configs: Dict[str, Any], model_type: str) -> Dict[str, TickerConfig]:
        ticker_configs: Dict[str, TickerConfig] = {}
        for ticker, params in raw_configs.items():
            if not isinstance(params, dict):
                continue
            if model_type == "heston":
                heston_params = params.get("heston", {})
                if isinstance(heston_params, dict):
                    ticker_configs[ticker] = TickerConfig(heston=HestonConfig(**heston_params))
            elif model_type == "gbm":
                gbm_params = params.get("gbm", {})
                if isinstance(gbm_params, dict):
                    ticker_configs[ticker] = TickerConfig(gbm=GBMConfig(**gbm_params))
        return ticker_configs

    @staticmethod
    def _resolve_path(path: str, base_path: str | None) -> str:
        if os.path.isabs(path):
            return path
        if base_path:
            return os.path.normpath(os.path.join(base_path, path))
        return path

    @staticmethod
    def _load_ticker_configs_from_csv(
        csv_path: str, model_type: str, base_path: str | None
    ) -> Dict[str, TickerConfig]:
        resolved_path = ConfigFactory._resolve_path(csv_path, base_path)
        if not os.path.isfile(resolved_path):
            raise FileNotFoundError(
                f"Ticker params CSV not found: {resolved_path}"
            )
        configs: Dict[str, TickerConfig] = {}
        with open(resolved_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                normalized = {key.lower(): (value or "").strip() for key, value in row.items()}
                ticker = normalized.get("ticker")
                if not ticker:
                    continue
                ticker_key = ticker.upper()

                # Extract start_price from the row if available
                start_price = None
                start_price_raw = normalized.get("start_price")
                if start_price_raw:
                    try:
                        start_price = float(start_price_raw)
                    except ValueError:
                        logging.warning(
                            "Invalid start_price %s for %s in %s",
                            start_price_raw, ticker_key, resolved_path
                        )

                if model_type == "heston":
                    fields: dict[str, float] = {}
                    for field in ("kappa", "theta", "xi", "rho"):
                        raw_value = normalized.get(field)
                        if not raw_value:
                            logging.warning(
                                "Skipping %s because %s is missing in %s",
                                ticker_key,
                                field,
                                resolved_path,
                            )
                            break
                        try:
                            fields[field] = float(raw_value)
                        except ValueError:
                            logging.warning(
                                "Skipping %s because %s is invalid in %s",
                                ticker_key,
                                field,
                                resolved_path,
                            )
                            break
                    else:
                        configs[ticker_key] = TickerConfig(heston=HestonConfig(**fields), start_price=start_price)
                elif model_type == "gbm":
                    mean_raw = normalized.get("mean") or normalized.get("mean_return")
                    sd_raw = normalized.get("sd") or normalized.get("volatility")
                    if not mean_raw or not sd_raw:
                        logging.warning(
                            "Skipping %s because GBM columns are missing in %s",
                            ticker_key,
                            resolved_path,
                        )
                        continue
                    try:
                        mean = float(mean_raw)
                        sd = float(sd_raw)
                    except ValueError:
                        logging.warning(
                            "Skipping %s because GBM values are invalid in %s",
                            ticker_key,
                            resolved_path,
                        )
                        continue
                    configs[ticker_key] = TickerConfig(gbm=GBMConfig(mean=mean, sd=sd), start_price=start_price)
                elif model_type == "gharch":
                    # Handle GHARCH model - check for required parameters
                    fields: dict[str, float | None] = {}
                    has_gharch_params = False
                    for field in ("omega", "alpha", "beta"):
                        raw_value = normalized.get(field)
                        if raw_value:
                            try:
                                fields[field] = float(raw_value)
                                has_gharch_params = True
                            except ValueError:
                                logging.warning(
                                    "Skipping %s because %s is invalid in %s",
                                    ticker_key,
                                    field,
                                    resolved_path,
                                )
                                break
                        else:
                            fields[field] = None
                    else:
                        if has_gharch_params:
                            initial_variance_raw = normalized.get("initial_variance")
                            initial_variance = None
                            if initial_variance_raw:
                                try:
                                    initial_variance = float(initial_variance_raw)
                                except ValueError:
                                    logging.warning(
                                        "Invalid initial_variance %s for %s in %s",
                                        initial_variance_raw, ticker_key, resolved_path
                                    )
                            fields["initial_variance"] = initial_variance
                            configs[ticker_key] = TickerConfig(gharch=GHARCHConfig(**fields), start_price=start_price)
        logging.info("Loaded %d tickers from %s", len(configs), resolved_path)
        return configs

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
