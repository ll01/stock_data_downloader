import argparse
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from functools import partial
from math import exp
from multiprocessing import Pool
from typing import Dict, List, Optional
import pandas as pd
from stock_data_downloader.config.logging_config import setup_logging
import websockets
import socket


# Load mean and standard deviation from a Parquet file
def load_stats_from_parquet(parquet_file: str, ticker: str) -> tuple[float, float]:
    """
    Load mean and standard deviation for a specific ticker from a Parquet file.
    """
    try:
        df = pd.read_parquet(parquet_file)
        stats = df[df["ticker"] == ticker].iloc[0]
        return stats["mean"], stats["sd"]
    except Exception as e:
        logging.error(f"Error loading stats from Parquet file: {e}")
        raise


# Simulate price using geometric Brownian motion
def simulate_price(mean: float, sd: float, start_price: float = 100.0) -> float:
    """
    Simulate a single price step using geometric Brownian motion.
    """
    return start_price * exp((mean - 0.5 * sd**2) + random.gauss() * sd)


def simulate_ohlc(mean: float, sd: float, start_price: float) -> Dict[str, float]:
    """
    Simulate OHLC data for a single timestep.
    """
    # Simulate the close price
    close = simulate_price(mean, sd, start_price)

    # Simulate open, high, and low prices
    open_price = start_price
    high = max(open_price, close) * (
        1 + random.uniform(0, sd / 2)
    )  # Add some volatility
    low = min(open_price, close) * (
        1 - random.uniform(0, sd / 2)
    )  # Add some volatility

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
    }


def simulate_single_ticker(ticker, ticker_stats, timesteps, start_price: float):
    prices = []
    current_price = start_price
    for _ in range(timesteps):
        mean, sd = ticker_stats["mean"], ticker_stats["sd"]
        ohlc = simulate_ohlc(mean, sd, current_price)
        prices.append(ohlc)
        current_price = ohlc["close"]
    return ticker, prices


# Simulate prices for multiple tickers over time
def simulate_prices(
    stats: Dict[str, Dict[str, float]],
    start_prices: Dict[str, float],
    timesteps: int = 100,
    interval: float = 1.0,
) -> Dict[str, List[float]]:
    """
    Simulate prices for multiple tickers over a given number of timesteps.
    Returns a dictionary of the form {ticker: [price1, price2, ...]}.
    """
    prices = {ticker: [] for ticker in stats.keys()}

    args = [
        (ticker, ticker_stats, timesteps, start_prices[ticker])
        for ticker, ticker_stats in stats.items()
    ]

    # Use multiprocessing to simulate prices for all tickers in parallel
    with Pool() as pool:
        results = pool.starmap(simulate_single_ticker, args)

    prices = {ticker: ticker_prices for ticker, ticker_prices in results}
    return prices


# Send simulated prices to a WebSocket
async def send_to_websocket(uri: str, prices: Dict[str, List[float]]):
    """
    Send simulated prices for multiple tickers to a WebSocket server.
    """

    max_lengh = max([len(prices) for prices in prices.values()])
    now = datetime.now()
    async with websockets.connect(uri) as websocket:
        for i in range(max_lengh):
            for ticker in prices.keys():
                current_price = prices[ticker][i] if i < len(prices[ticker]) else None
                current_time = (now + timedelta(days=1)).isoformat()
                if current_price is not None:
                    data = {
                        "timestamp": current_time,
                        "ticker": ticker,
                        "price": current_price,
                    }
                    await websocket.send(json.dumps(data))


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


def find_free_port():
    """Finds a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))  # Bind to any available port
        return s.getsockname()[1]


async def run_simulation(args: argparse.Namespace) -> Dict[str, List[Dict[str, float]]]:
    """Runs the price simulation based on the provided arguments."""
    try:
        df = pd.read_parquet(args.parquet_file)
        stats = {}
        start_prices = {}
        for _, row in df.iterrows():
            ticker = row["ticker"]
            stats[ticker] = {"mean": row["mean"], "sd": row["sd"]}
            start_prices[ticker] = args.start_price

        return simulate_prices(stats, start_prices, args.timesteps, args.interval)

    except FileNotFoundError:
        logging.error(f"Parquet file not found: {args.parquet_file}")
        return None  # Or raise an exception if you prefer
    except Exception as e:
        logging.exception(f"Error during simulation setup: {e}")
        return None


def save_to_parquet(
    simulated_prices: Dict[str, List[Dict[str, float]]], output_file: str
):
    """Saves the simulated prices to a Parquet file."""
    try:
        dfs = []
        for ticker, ohlc_data in simulated_prices.items():
            ticker_df = pd.DataFrame(ohlc_data)
            ticker_df["ticker"] = ticker
            dfs.append(ticker_df)
        final_df = pd.concat(dfs, ignore_index=True)
        final_df.to_parquet(output_file)
        logging.info(f"Simulated data saved to {output_file}")
    except Exception as e:
        logging.exception(f"Error saving to Parquet: {e}")


async def handle_websocket_output(
    simulated_prices: Dict[str, List[Dict[str, float]]], websocket_uri: Optional[str]
):
    """Handles sending simulated prices to a WebSocket."""
    if websocket_uri:
        uri = websocket_uri
    else:
        port = find_free_port()
        uri = f"ws://localhost:{port}"
        logging.info(f"Starting WebSocket server on {uri}")

        async def websocket_server(websocket, path):
            await send_to_websocket(uri, simulated_prices)
            try:
                while True:
                    await asyncio.sleep(1)
            except websockets.exceptions.ConnectionClosedOK:
                pass

        async with websockets.serve(websocket_server, "localhost", port):
            await asyncio.Future()  # run forever

    await send_to_websocket(uri, simulated_prices)


async def main():
    args = parse_arguments()
    setup_logging(args.log_level)

    simulated_prices = await run_simulation(args)

    if simulated_prices:  # Check if simulation was successful
        if args.output_format == "parquet":
            save_to_parquet(simulated_prices, args.output_file)
        elif args.output_format == "websocket":
            await handle_websocket_output(simulated_prices, args.websocket_uri)


if __name__ == "__main__":
    asyncio.run(main())
