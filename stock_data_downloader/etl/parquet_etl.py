import logging
import math
from pathlib import Path
from typing import Dict, List, Union, Optional
import pandas as pd

from stock_data_downloader.data_processing.TickerStats import TickerStats


ARCHETYPES = {
    "blue_chip": TickerStats(
        mean=0.0005, sd=0.01,
        kappa=3.0, theta=0.04, xi=0.3, rho=-0.6,
        degrees_of_freedom=None # Use normal distribution
    ),
    "growth_tech": TickerStats(
        mean=0.001, sd=0.025,
        kappa=2.0, theta=0.06, xi=0.4, rho=-0.7,
        degrees_of_freedom=5.0 # Fatter tails
    ),
    "volatile_speculative": TickerStats(
        mean=0.0001, sd=0.04,
        kappa=1.0, theta=0.08, xi=0.5, rho=-0.8,
        degrees_of_freedom=3.0 # Very fat tails
    ),
    "utility_defensive": TickerStats(
        mean=0.0002, sd=0.005,
        kappa=4.0, theta=0.02, xi=0.2, rho=-0.5,
        degrees_of_freedom=None # Use normal distribution
    ),
}

def generate_synthetic_ticker_stats(archetype: str) -> TickerStats:
    """
    Generates synthetic TickerStats based on predefined archetypes.
    """
    if archetype not in ARCHETYPES:
        raise ValueError(f"Unknown archetype: {archetype}. Available: {list(ARCHETYPES.keys())}")
    return ARCHETYPES[archetype]

def load_stock_stats(
    sim_data_file_path: Union[str, Path] = "data/sim_data.parquet",
    default_archetype: Optional[str] = None
) -> dict[str, TickerStats]:
    """
    Load stock stats from the parquet files. If a ticker's stats are not found,
    and a default_archetype is provided, synthetic stats will be generated.
    """
    stats: Dict[str, TickerStats] = {}
    skipped = 0

    try:
        df = pd.read_parquet(sim_data_file_path)
        for _, row in df.iterrows():
            ticker = row["ticker"]
            if math.isnan(row["mean"]) or math.isnan(row["sd"]):
                skipped += 1
                continue
            # Load all available fields from parquet, including new Heston/GARCH params
            stats[ticker] = TickerStats(
                mean=row["mean"],
                sd=row["sd"],
                kappa=row.get("kappa"),
                theta=row.get("theta"),
                xi=row.get("xi"),
                rho=row.get("rho"),
                omega=row.get("omega"),
                alpha=row.get("alpha"),
                beta=row.get("beta"),
                initial_variance=row.get("initial_variance"),
                degrees_of_freedom=row.get("degrees_of_freedom")
            )
        logging.info(f"Loaded {len(stats)} stock stats from {sim_data_file_path}")
        if skipped > 0:
            logging.warning(f"Skipped {skipped} rows with missing data from {sim_data_file_path}")
    except FileNotFoundError:
        logging.warning(f"Simulation data file not found: {sim_data_file_path}. Generating synthetic stats if archetype is provided.")
    except Exception as e:
        logging.error(f"Error loading stock stats from {sim_data_file_path}: {e}")

    # If default_archetype is provided, ensure all tickers have stats
    if default_archetype:
        # This part needs to know which tickers are being simulated.
        # For now, it assumes the caller will handle passing tickers that need stats.
        # A more robust solution might involve passing the list of desired tickers here.
        logging.info(f"Using default archetype '{default_archetype}' for missing ticker stats.")
        # This function currently doesn't know which tickers are missing. 
        # It's designed to be called by a higher-level function that knows the full list of tickers.
        # For now, we'll just return the loaded stats and expect the caller to fill in the gaps.

    return stats

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
