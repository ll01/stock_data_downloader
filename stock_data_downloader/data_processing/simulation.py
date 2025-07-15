from datetime import datetime, timedelta, timezone
from math import exp, sqrt
import random
from multiprocessing import Pool
from typing import Dict, List, Optional
import numpy as np


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
    for _ in range(timesteps):
        # Seed the local RNG based on the timestep to ensure consistent randomness
        # for each timestep across different runs with the same initial seed.
        ohlc = simulate_ohlc(ticker_stats.mean, ticker_stats.sd, rng, current_price, interval)
        prices.append(ohlc)
        current_price = ohlc["close"]
    return ticker, prices


def simulate_prices(
    stats: Dict[str, TickerStats],
    start_prices: Dict[str, float],
    timesteps: int = 100,
    interval: float = 1.0,
    seed: Optional[int] = None,  # Add a seed for overall reproducibility
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


def simulate_heston_prices(
    stats: Dict[str, TickerStats],
    start_prices: Dict[str, float],
    timesteps: int,
    dt: float,  # Time step size (e.g., 1/252 for daily)
    seed: Optional[int] = None
) -> Dict[str, List[Dict[str, float]]]:
    """
    Simulates stock prices using the Heston model for stochastic volatility.

    Args:
        stats: A dictionary mapping tickers to TickerStats objects.
               These stats must include Heston parameters:
               - mu (drift)
               - kappa (mean-reversion speed of variance)
               - theta (long-run average variance)
               - xi (volatility of variance, or "vol of vol")
               - rho (correlation between asset and variance processes)
        start_prices: Dictionary of starting prices for each ticker.
        timesteps: The number of simulation steps.
        dt: The time increment for each step.
        seed: Random seed for reproducibility.

    Returns:
        A dictionary mapping each ticker to a list of OHLCV dictionaries.
    """
    if seed is not None:
        np.random.seed(seed)

    simulated_data = {ticker: [] for ticker in start_prices}

    for ticker, start_price in start_prices.items():
        ticker_stats = stats.get(ticker)
        if not ticker_stats:
            raise ValueError(f"No stats found for ticker: {ticker}")

        # Extract Heston parameters from TickerStats
        mu = getattr(ticker_stats, 'mu', 0.0)
        kappa = getattr(ticker_stats, 'kappa', 3.0)
        theta = getattr(ticker_stats, 'theta', 0.04) # Long-run variance (e.g., 0.2^2)
        xi = getattr(ticker_stats, 'xi', 0.3) # Vol of vol
        rho = getattr(ticker_stats, 'rho', -0.6) # Correlation
        degrees_of_freedom = getattr(ticker_stats, 'degrees_of_freedom', None)
        
        # Initial variance can be the long-run average
        v0 = theta 
        
        prices = [start_price]
        variances = [v0]

        # Generate correlated random walks
        corr_matrix = np.array([[1, rho], [rho, 1]])
        chol_matrix = np.linalg.cholesky(corr_matrix)
        
        # Generate random numbers for both processes at once
        if degrees_of_freedom is not None:
            random_shocks = np.random.standard_t(degrees_of_freedom, size=(timesteps, 2))
        else:
            random_shocks = np.random.normal(size=(timesteps, 2))
        correlated_shocks = random_shocks @ chol_matrix.T

        price_shocks = correlated_shocks[:, 0]
        variance_shocks = correlated_shocks[:, 1]
        
        for i in range(1, timesteps):
            # Previous values
            last_price = prices[-1]
            last_variance = variances[-1]

            # Ensure variance is non-negative (Full Truncation scheme)
            last_variance = max(last_variance, 0)
            
            # Update variance (CIR process)
            dv = kappa * (theta - last_variance) * dt + xi * np.sqrt(last_variance) * np.sqrt(dt) * variance_shocks[i]
            new_variance = last_variance + dv
            variances.append(new_variance)

            # Update price
            dp = mu * last_price * dt + np.sqrt(last_variance) * last_price * np.sqrt(dt) * price_shocks[i]
            new_price = last_price + dp
            prices.append(new_price)

        # Convert to OHLCV format (simplified for this example)
        now = datetime.now(timezone.utc)
        for i in range(len(prices)):
            price = prices[i]
            # Simple OHLC generation from price points
            open_price = prices[i-1] if i > 0 else price
            high_price = max(open_price, price) + np.random.uniform(0, 0.01) * price
            low_price = min(open_price, price) - np.random.uniform(0, 0.01) * price
            step_duration_in_days = dt * 252 
            current_time = now + timedelta(days=i * step_duration_in_days)
            simulated_data[ticker].append({
                "timestamp": current_time.isoformat(),
                "ticker": ticker,
                "open": open_price,
                "high": high_price,
                "low": low_price,   
                "close": price,
                "volume": np.random.randint(10000, 50000) # Synthetic volume
            })

    return simulated_data