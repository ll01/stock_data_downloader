import logging
import math
from pathlib import Path
from typing import Dict, List, Union
import pandas as pd

from stock_data_downloader.data_processing.TickerStats import TickerStats



def load_stock_stats(
    sim_data_file_path: Union[str, Path] = "data/sim_data.parquet"
) -> dict[str, TickerStats]:
    """
    Load stock stats from the parquet files.
    """
    df = pd.read_parquet(sim_data_file_path)
    stats: Dict[str, TickerStats] = {}
    skipped = 0
    for _, row in df.iterrows():
        ticker = row["ticker"]
        if math.isnan(row["mean"]) or math.isnan(row["sd"]):
            skipped = skipped + 1
            continue
        stats[ticker] = TickerStats(mean=row["mean"], sd=row["sd"])
    logging.info(f"Loaded {len(stats)} stock stats from {sim_data_file_path}")
    if skipped > 0:
        logging.warning(f"Skipped {skipped} rows with missing data")
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
