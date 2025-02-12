import argparse


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for the price simulation script."""
    parser = argparse.ArgumentParser(
        description="Simulate stock prices for multiple tickers using geometric Brownian motion."
    )

    # Input/Output options
    parser.add_argument(
        "--parquet-file",
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
        "--timesteps",
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
        default=1.0,  # Default interval of 1 second (or whatever unit you're using)
        help="Time interval between timesteps (default: 1.0)",
    )

    return parser.parse_args()