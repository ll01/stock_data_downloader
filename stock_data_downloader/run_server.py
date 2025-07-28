import argparse
import asyncio
import logging
from typing import Dict, Any

from stock_data_downloader.config.logging_config import setup_logging
from stock_data_downloader.etl.parquet_etl import load_stock_stats
from stock_data_downloader.models import (
    AppConfig, 
    DataSourceConfig, 
    BacktestDataSourceConfig,
    TickerConfig,
    HestonConfig,
    GBMConfig
)
from stock_data_downloader.websocket_server.factories.ConfigFactory import ConfigFactory
from stock_data_downloader.websocket_server.factories.serverFactory import start_server_from_config


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Start trading server using configuration file")
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to configuration file (JSON or YAML)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level"
    )
    parser.add_argument(
        "--sim-data-file",
        type=str,
        help="Path to stock statistics data file (for Brownian simulation)"
    )
    parser.add_argument(
        "--start-price",
        type=float,
        default=100.0,
        help="Starting price for all assets in simulation mode"
    )
    return parser.parse_args()


def is_valid_file_path(file_path: str) -> bool:
    """Check if the file path is valid (not None, empty, or the string 'None')."""
    return file_path is not None and file_path.strip() != "" and file_path.lower() != "none"


def generate_basic_start_prices(
    starting_price: float, tickers_or_stats: Dict[str, Any]
) -> Dict[str, float]:
    """Generates basic starting prices for each ticker."""
    return {ticker: starting_price for ticker in tickers_or_stats.keys()}


async def main():
    """Main entry point for the application."""
    # Parse command-line arguments
    args = parse_arguments()
    
    # Set up logging
    setup_logging(args.log_level)
    logging.info(f"Loading configuration from {args.config}")
    logging.debug(f"Log Level {args.log_level}")
    
    # Load configuration
    try:
        # Load configuration using ConfigFactory
        config = ConfigFactory.load_config(args.config)
        
        # Handle command-line overrides for backtest data sources
        if (config.data_source.source_type == "backtest" and 
            isinstance(config.data_source.config, BacktestDataSourceConfig)):
            
            backtest_config = config.data_source.config
            
            # Check if we have a valid simulation data file to override config
            if is_valid_file_path(args.sim_data_file):
                logging.info(f"Loading stock statistics from {args.sim_data_file}")
                stats = load_stock_stats(args.sim_data_file)
                
                # Generate ticker configs from stats
                ticker_configs = {}
                for ticker, stat in stats.items():
                    if backtest_config.backtest_model_type == "heston":
                        ticker_configs[ticker] = TickerConfig(
                            heston=HestonConfig(
                                kappa=stat.kappa or 1.0,
                                theta=stat.theta or 0.04,
                                xi=stat.xi or 0.2,
                                rho=stat.rho or -0.5
                            )
                        )
                    elif backtest_config.backtest_model_type == "gbm":
                        ticker_configs[ticker] = TickerConfig(
                            gbm=GBMConfig(
                                mean=stat.mean,
                                sd=stat.sd
                            )
                        )
                
                # Generate start prices
                start_prices = generate_basic_start_prices(args.start_price, stats)
                
                # Update the backtest config
                backtest_config.ticker_configs = ticker_configs
                backtest_config.start_prices = start_prices
            
            # Otherwise, check if we need to generate start prices from existing ticker configs
            elif backtest_config.ticker_configs and not backtest_config.start_prices:
                logging.warning("No start_prices found in config for ticker_configs. Generating basic start prices.")
                start_prices = generate_basic_start_prices(args.start_price, backtest_config.ticker_configs)
                backtest_config.start_prices = start_prices
        
        # Start the server
        logging.info("Starting server...")
        await start_server_from_config(config)
        
    except Exception as e:
        logging.error(f"Error starting server: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped by user.")
    except Exception as e:
        logging.error(f"Unhandled exception: {e}", exc_info=True)