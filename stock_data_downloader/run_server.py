import argparse
import asyncio
import logging
from typing import Dict

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


def generate_basic_start_prices(
    starting_price: float, stats: Dict[str, TickerStats]
) -> Dict[str, float]:
    """Generates basic starting prices for each ticker."""
    return {ticker: starting_price for ticker, _ in stats.items()}


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
        ticker_configs = config.get("data_source", {}).get("ticker_configs", [])
        print(f"Data source name: {ticker_configs}")
        if not data_source_name:
            logging.error("No data source name provided in configuration.")
            raise ValueError("No data source name provided in configuration.")
        # If using Brownian simulation, load stock statistics
        if simulation_enabled and data_source_name.lower() == "backtest":
            if not args.sim_data_file and not ticker_configs:
                logging.warning("No simulation data file or ticker configs provided. Using empty stats.")
                raise ValueError("No simulation data file or ticker configs provided.")
            else:
                logging.info(f"Loading stock statistics from {args.sim_data_file}")
                stats = load_stock_stats(args.sim_data_file)
                
            # Generate starting prices
            start_prices = generate_basic_start_prices(args.start_price, stats)
            
            # Update config with stats and start prices
            config["data_source"]["stats"] = stats
            config["data_source"]["start_prices"] = start_prices
        
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