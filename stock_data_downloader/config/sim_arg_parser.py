import argparse


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for the price simulation script."""
    parser = argparse.ArgumentParser(
        description="Simulate stock prices for multiple tickers using geometric Brownian motion."
    )

    # Input/Output options
    parser.add_argument(
        "--sim_data_file",
        type=str,
        default="data/sim_data.parquet",
        help="Path to the Parquet file containing ticker statistics (default: sim_data.parquet)",
    )

    parser.add_argument(
        "--websocket-uri",
        type=str,
        default=None,
        help="WebSocket URI to send simulated data. If not provided, a free port will be found and used.",
    )

    parser.add_argument(
        "--output-format",
        type=str,
        choices=["parquet", "websocket"],
        default="parquet",  # Changed default to parquet
        help="Output format for the simulation results (parquet or websocket).",
    )

    parser.add_argument(
        "--output-file",  # New argument for parquet output
        type=str,
        default="simulated_prices.parquet",
        help="Path to save the simulated prices in parquet format. Only used if output-format is parquet",
    )

    # Simulation parameters
    parser.add_argument(
        "--time-steps",
        type=int,
        default=100,
        help="Number of timesteps to simulate (default: 100)",
    )
    parser.add_argument(
        "--start-price",
        type=float,
        default=100.0,
        help="Starting price for all tickers (default: 100.0)",
    )

    # Logging options
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
    )

    # Simulation interval
    parser.add_argument(
        "--interval",
        type=float,
        default=1,  # Default interval of 1 day
        help="Time interval between timesteps (default: 1)",
    )
    
    parser.add_argument(
        "--realtime",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Whether to simulate realtime prices (default: False)",
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (default: None)",
    )


    return parser.parse_args()


#example
# python -m stock_data_downloader.sim --output-format websocket --sim_data_file C:\Users\enti2\programming\trading_bot\stock_data_downloader\stock_data_downloader\data\sim_data.parquet