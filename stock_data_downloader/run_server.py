import argparse
import asyncio
import logging
from typing import Dict, Any

from stock_data_downloader.config.logging_config import setup_logging
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.etl.parquet_etl import load_stock_stats
from stock_data_downloader.websocket_server.ConfigHandler import ConfigHandler
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
        default="INFO",
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
    
    # Load configuration
    try:
        config = ConfigHandler.load_config(args.config)
        
        # Check if we're in simulation mode with Brownian data source
        simulation_enabled = config.get("simulation", {}).get("enabled", True)
        data_source_name: str = config.get("data_source", {}).get("name", None)
        ticker_configs = config.get("data_source", {}).get("ticker_configs", {})
        
        if not data_source_name:
            logging.error("No data source name provided in configuration.")
            raise ValueError("No data source name provided in configuration.")
        
        # Initialize stats and start_prices
        stats: Dict[str, TickerStats] = {}
        start_prices: Dict[str, float] = {}
        
        # If using backtest data source, determine data source method
        if simulation_enabled and data_source_name.lower() == "backtest":
            # Check if we have a valid simulation data file
            if is_valid_file_path(args.sim_data_file):
                logging.info(f"Loading stock statistics from {args.sim_data_file}")
                stats = load_stock_stats(args.sim_data_file)
                start_prices = generate_basic_start_prices(args.start_price, stats)
                config["data_source"]["stats"] = stats
                config["data_source"]["start_prices"] = start_prices
            
            # Otherwise, check if we have ticker configs
            elif ticker_configs:
                logging.info("Using ticker configs from configuration to determine start prices.")
                # DataSourceFactory will handle TickerConfig creation from ticker_configs
                # We just need to ensure start_prices are available
                start_prices = config.get("data_source", {}).get("start_prices", {})
                if not start_prices:
                    logging.warning("No start_prices found in config for ticker_configs. Generating basic start prices.")
                    start_prices = generate_basic_start_prices(args.start_price, ticker_configs)
                config["data_source"]["start_prices"] = start_prices
            
            # Neither valid file nor ticker configs available
            else:
                logging.error("No valid simulation data file or ticker configs provided for backtest mode.")
                raise ValueError("No valid simulation data file or ticker configs provided.")
        
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