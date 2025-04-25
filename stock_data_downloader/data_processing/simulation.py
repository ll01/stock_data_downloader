from math import exp, sqrt
import random
from multiprocessing import Pool
from typing import Dict, List, Optional


from stock_data_downloader.data_processing.TickerStats import TickerStats


def calculate_geometric_brownian_motion(
    mean: float, sd: float, rng: random.Random, start_price: float = 100.0, interval: float = 1.0
) -> float:
    """
    Simulate a single price step using geometric Brownian motion.
    """
    return start_price * exp((mean - 0.5 * sd**2) * interval + rng.gauss(0, 1) * sd * sqrt(interval))


def simulate_ohlc(
    mean: float, sd: float, rng: random.Random, start_price: float, interval: float
) -> Dict[str, float]:
    """
    Simulate OHLC data for a single timestep.
    """
    close = calculate_geometric_brownian_motion(mean, sd, rng, start_price, interval)

    open_price = start_price
    intraperiod_vol = sd * sqrt(interval) * 0.5
    high = max(open_price, close) * (1 + abs(rng.gauss(0, 1)) * intraperiod_vol)
    low = min(open_price, close) * (1 - abs(rng.gauss(0, 1)) * intraperiod_vol)

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
    }


def simulate_single_ticker(
    ticker: str,
    ticker_stats: TickerStats,
    timesteps: int,
    start_price: float,
    interval: float,
    seed: Optional[int],
) -> tuple[str, List[Dict[str, float]]]:
    """_summary_
    simulate_single_ticker simulates the price of a single ticker over a given number of timesteps.

    Returns:
        tuple[str, List[float]]: _description_
    """
    prices: List[Dict[str, float]] = []
    current_price = start_price
    rng = random.Random(seed)  # Create a local random number generator
    for i in range(timesteps):
        # Seed the local RNG based on the timestep to ensure consistent randomness
        # for each timestep across different runs with the same initial seed.
        if seed:
            timestep_seed = seed + i
            rng.seed(timestep_seed)
        ohlc = simulate_ohlc(ticker_stats.mean, ticker_stats.sd, rng, current_price, interval)
        prices.append(ohlc)
        current_price = ohlc["close"]
    return ticker, prices


def simulate_prices(
    stats: Dict[str, TickerStats],
    start_prices: Dict[str, float],
    timesteps: int = 100,
    interval: float = 1.0,
    seed: Optional[int] = 42,  # Add a seed for overall reproducibility
) -> Dict[str, List[Dict[str, float]]]:
    """
    Simulate prices for multiple tickers over a given number of timesteps.
    Returns a dictionary of the form {ticker: [price1, price2, ...]}.
    """
    prices = {ticker: [] for ticker in stats.keys()}

    args = []
    ticker_list = list(stats.keys())  # Create a list of tickers
    for i in range(len(ticker_list)):
        ticker = ticker_list[i]
        ticker_stats = stats[ticker]
        if seed is not None:
            ticker_seed = seed + i
        else:
            ticker_seed = None

        args.append((ticker, ticker_stats, timesteps, start_prices[ticker], interval, ticker_seed))

    with Pool() as pool:
        results = pool.starmap(simulate_single_ticker, args)

    prices = {ticker: ticker_prices for ticker, ticker_prices in results}
    return prices