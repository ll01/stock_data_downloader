from datetime import datetime, timedelta, timezone
from math import exp, sqrt
import random
from typing import Dict, List, Optional, Generator
import numpy as np
from datetime import datetime, timedelta, timezone

from stock_data_downloader.data_processing.TickerStats import TickerStats


def _calculate_gbm_step(
    mean: float, sd: float, rng: random.Random, last_price: float, interval: float
) -> float:
    """Simulate a single price step using geometric Brownian motion."""
    return last_price * exp(
        (mean - 0.5 * sd**2) * interval + rng.gauss(0, 1) * sd * sqrt(interval)
    )


def generate_gbm_ticks(
    stats: Dict[str, TickerStats],
    start_prices: Dict[str, float],
    timesteps: int = 100,
    interval: float = 1.0,
    seed: Optional[int] = None,
) -> Generator[List[Dict[str, any]], None, None]:
    """
    A generator that simulates prices for multiple tickers using Geometric Brownian Motion,
    yielding the data for one timestep at a time.

    Args:
        stats: A dictionary mapping tickers to their statistical properties (mean, sd).
        start_prices: A dictionary of starting prices for each ticker.
        timesteps: The total number of steps to simulate.
        interval: The time interval for each step (e.g., 1.0 for a day).
        seed: An optional random seed for reproducibility.

    Yields:
        A list of dictionaries, where each dictionary represents the OHLCV data
        for a single ticker at the current timestep.
    """
    rng = random.Random(seed)
    current_prices = start_prices.copy()
    start_time = datetime.now(timezone.utc)

    for i in range(timesteps):
        timestep_data = []
        # Assumes 252 trading days in a year to convert interval to a calendar duration
        step_duration_in_days = interval * 252
        current_timestamp = start_time + timedelta(days=(i * step_duration_in_days))

        for ticker, ticker_stats in stats.items():
            last_price = current_prices[ticker]
            
            # Simulate the next closing price
            close_price = _calculate_gbm_step(
                ticker_stats.mean, ticker_stats.sd, rng, last_price, interval
            )

            # Simplified OHLC generation for the step
            open_price = last_price
            intraperiod_vol = ticker_stats.sd * sqrt(interval) * 0.5
            high_price = max(open_price, close_price) * (
                1 + abs(rng.gauss(0, 1)) * intraperiod_vol
            )
            low_price = min(open_price, close_price) * (
                1 - abs(rng.gauss(0, 1)) * intraperiod_vol
            )

            # Standardized output dictionary
            tick_data = {
                "ticker": ticker,
                "timestamp": current_timestamp.isoformat(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": rng.randint(10000, 50000),  # Synthetic volume
            }
            timestep_data.append(tick_data)

            # Update the current price for the next iteration
            current_prices[ticker] = close_price
        
        yield timestep_data


def generate_heston_ticks(
    stats: Dict[str, TickerStats],
    start_prices: Dict[str, float],
    timesteps: int,
    dt: float,  # Time step size (e.g., 1/252 for daily)
    seed: Optional[int] = None,
) -> Generator[List[Dict[str, any]], None, None]:
    """
    A generator that simulates stock prices using the Heston model,
    yielding the data for one timestep at a time.

    Args:
        stats: A dictionary mapping tickers to TickerStats objects with Heston parameters.
        start_prices: Dictionary of starting prices for each ticker.
        timesteps: The number of simulation steps.
        dt: The time increment for each step as a fraction of a year.
        seed: Random seed for reproducibility.

    Yields:
        A list of dictionaries, where each dictionary represents the OHLCV data
        for a single ticker at the current timestep.
    """
    if seed is not None:
        np.random.seed(seed)

    # --- Initialize state for all tickers ---
    current_prices = start_prices.copy()
    # Initialize variance for each ticker to its long-run average (theta)
    current_variances = {
        ticker: s.theta for ticker, s in stats.items() if s.theta is not None
    }
    start_time = datetime.now(timezone.utc)

    for i in range(timesteps):
        timestep_data = []
        # Assumes 252 trading days in a year to convert dt to a calendar duration
        step_duration_in_days = dt * 252
        current_timestamp = start_time + timedelta(days=(i * step_duration_in_days))

        for ticker, ticker_stats in stats.items():
            if ticker not in current_prices or ticker not in current_variances:
                continue

            # --- Extract Heston parameters ---
            mu = getattr(ticker_stats, "mu", 0.0)
            kappa = getattr(ticker_stats, "kappa", 3.0)
            theta = getattr(ticker_stats, "theta", 0.04)
            xi = getattr(ticker_stats, "xi", 0.3)
            rho = getattr(ticker_stats, "rho", -0.6)
            
            # --- Correlated random shocks for this step ---
            corr_matrix = np.array([[1, rho], [rho, 1]])
            chol_matrix = np.linalg.cholesky(corr_matrix)
            random_shocks = np.random.normal(size=2)
            correlated_shocks = random_shocks @ chol_matrix.T
            price_shock = correlated_shocks[0]
            variance_shock = correlated_shocks[1]

            # --- Get previous values ---
            last_price = current_prices[ticker]
            last_variance = max(current_variances[ticker], 0)  # Full Truncation

            # --- Update variance (CIR process) ---
            dv = (
                kappa * (theta - last_variance) * dt
                + xi * np.sqrt(last_variance) * np.sqrt(dt) * variance_shock
            )
            new_variance = last_variance + dv
            current_variances[ticker] = new_variance

            # --- Update price ---
            dp = (
                mu * last_price * dt
                + np.sqrt(last_variance) * last_price * np.sqrt(dt) * price_shock
            )
            new_price = last_price + dp
            current_prices[ticker] = new_price

            # --- Simplified OHLC generation ---
            open_price = last_price
            high_price = max(open_price, new_price) + np.random.uniform(0, 0.01) * new_price
            low_price = min(open_price, new_price) - np.random.uniform(0, 0.01) * new_price

            # --- Standardized output ---
            tick_data = {
                "ticker": ticker,
                "timestamp": current_timestamp.isoformat(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": new_price,
                "volume": np.random.randint(10000, 50000),
            }
            timestep_data.append(tick_data)

        yield timestep_data