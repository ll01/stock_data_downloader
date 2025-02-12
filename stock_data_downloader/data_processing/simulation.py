import logging
from math import exp
from pathlib import Path
import random
from multiprocessing import Pool
from typing import Dict, List, Union

import pandas as pd

# Simulate price using geometric Brownian motion
def simulate_price(mean: float, sd: float, start_price: float = 100.0, interval: float = 1.0) -> float:
    """
    Simulate a single price step using geometric Brownian motion.
    """
    return start_price * exp((mean - 0.5 * sd**2) * interval + random.gauss() * sd)


def simulate_ohlc(mean: float, sd: float, start_price: float, interval: float) -> Dict[str, float]:
    """
    Simulate OHLC data for a single timestep.
    """
    # Simulate the close price
    close = simulate_price(mean, sd, start_price, interval)

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


def simulate_single_ticker(ticker, ticker_stats, timesteps, start_price: float, interval: float) -> tuple[str, List[float]]:
    prices = []
    current_price = start_price
    for _ in range(timesteps):
        mean, sd = ticker_stats["mean"], ticker_stats["sd"]
        ohlc = simulate_ohlc(mean, sd, current_price, interval)
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


async def run_simulation(start_price: int, timesteps: int, interval: float, sim_data_file_path: Union[str, Path]) -> Dict[str, List[Dict[str, float]]]:
    """Runs the price simulation based on the provided arguments."""
    try:
        df = pd.read_parquet(sim_data_file_path)
        stats = {}
        start_prices = {}
        for _, row in df.iterrows():
            ticker = row["ticker"]
            stats[ticker] = {"mean": row["mean"], "sd": row["sd"]}
            start_prices[ticker] = start_price

        return simulate_prices(stats, start_prices, timesteps, interval)

    except FileNotFoundError:
        logging.error(f"Parquet file not found: {sim_data_file_path}")
        raise FileNotFoundError
    except Exception as e:
        logging.exception(f"Error during simulation setup: {e}")
        raise e