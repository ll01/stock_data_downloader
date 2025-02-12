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
        help="WebSocket URI to send simulated data (required if output-format is websocket)",
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

    return parser.parse_args()