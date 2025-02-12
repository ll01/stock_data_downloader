import logging
from math import exp
from pathlib import Path
import random
from multiprocessing import Pool
from typing import Dict, List, Union

import pandas as pd

from stock_data_downloader.data_processing.TickerStats import TickerStats


def calculate_geometric_brownian_motion(
    mean: float, sd: float, start_price: float = 100.0, interval: float = 1.0
) -> float:
    """
    Simulate a single price step using geometric Brownian motion.
    """
    return start_price * exp((mean - 0.5 * sd**2) * interval + random.gauss() * sd)


def simulate_ohlc(
    mean: float, sd: float, start_price: float, interval: float
) -> Dict[str, float]:
    """
    Simulate OHLC data for a single timestep.
    """
    close = calculate_geometric_brownian_motion(mean, sd, start_price, interval)

    open_price = start_price
    high = max(open_price, close) * (1 + random.uniform(0, sd / 2))
    low = min(open_price, close) * (1 - random.uniform(0, sd / 2))

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
    }


def simulate_single_ticker(
    ticker: str,
    ticker_stats: Dict[str, float],
    timesteps: int,
    start_price: float,
    interval: float,
) -> tuple[str, List[Dict[str, float]]]:
    """_summary_
    simulate_single_ticker simulates the price of a single ticker over a given number of timesteps.

    Returns:
        tuple[str, List[float]]: _description_
    """
    prices: List[Dict[str, float]] = []
    current_price = start_price
    for _ in range(timesteps):
        mean, sd = ticker_stats["mean"], ticker_stats["sd"]
        ohlc = simulate_ohlc(mean, sd, current_price, interval)
        prices.append(ohlc)
        current_price = ohlc["close"]
    return ticker, prices


def simulate_prices(
    stats: Dict[str, TickerStats],
    start_prices: Dict[str, float],
    timesteps: int = 100,
    interval: float = 1.0,
) -> Dict[str, List[Dict[str, float]]]:
    """
    Simulate prices for multiple tickers over a given number of timesteps.
    Returns a dictionary of the form {ticker: [price1, price2, ...]}.
    """
    prices = {ticker: [] for ticker in stats.keys()}

    args = [
        (ticker, ticker_stats, timesteps, start_prices[ticker], interval)
        for ticker, ticker_stats in stats.items()
    ]

    with Pool() as pool:
        results = pool.starmap(simulate_single_ticker, args)

    prices = {ticker: ticker_prices for ticker, ticker_prices in results}
    return prices