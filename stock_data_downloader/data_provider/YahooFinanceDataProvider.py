import logging
import os
import platform
from pathlib import Path
from typing import List, Optional

import pandas as pd
import yfinance as yf
from pyrate_limiter import Duration, Limiter, RequestRate
from requests import Session
from requests_cache import CacheMixin, SQLiteCache
from requests_ratelimiter import LimiterMixin, MemoryQueueBucket

from stock_data_downloader.data_provider.DataProvider import DataProvider
from stock_data_downloader.data_provider.OutlierIdentifier import OutlierIdentifier

logger = logging.getLogger(__name__)


class CachedLimiterSession(CacheMixin, LimiterMixin, Session): # type: ignore
    """
    A custom session class that combines caching and rate-limiting.
    This class explicitly handles the type mismatch between `requests.Session` and `CacheMixin`.
    """
    pass

def get_default_cache_location() -> Path:
    """
    Get the default cache location based on the operating system.
    """
    system = platform.system()
    user = os.getenv("USER") or os.getenv("USERNAME")

    if system == "Windows":
        return Path(f"C:/Users/{user}/AppData/Local/py-yfinance")
    elif system == "Linux":
        return Path(f"/home/{user}/.cache/py-yfinance")
    elif system == "Darwin":  # macOS
        return Path(f"/Users/{user}/Library/Caches/py-yfinance")
    else:
        raise OSError(f"Unsupported operating system: {system}")


def set_cache_location(custom_location: Optional[str] = None) -> Path:
    """
    Set the cache location for yfinance.
    If no custom location is provided, use the default location.
    """
    if custom_location:
        cache_dir = Path(custom_location)
    else:
        cache_dir = get_default_cache_location()

    # Create the cache directory if it doesn't exist
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Set the cache location for yfinance
    yf.set_tz_cache_location(str(cache_dir))

    logger.info(f"Cache location set to: {cache_dir}")
    return cache_dir


class YahooFinanceDataProvider(DataProvider):
    def __init__(
        self, requests_per_minute: int, tz_custom_cache_location: Optional[str] = None
    ):
        """
        Initialize the data provider with rate limiting and caching.
        """
        self.session = CachedLimiterSession(
            limiter=Limiter(
                RequestRate(
                    1, Duration.SECOND
                )  # Rate limit per minute
            ),
            bucket_class=MemoryQueueBucket,
            backend=SQLiteCache("yfinance.cache"),  # Cache stored in SQLite database
        )
        set_cache_location(tz_custom_cache_location)

    def download_ticker_data(
        self, tickers: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Downloads historical stock data from Yahoo Finance with rate limiting and caching.
        """
        logger.info(
            f"Downloading data for {len(tickers)} tickers from {start_date} to {end_date}..."
        )

        try:
            # Download data for all tickers at once
            data = yf.download(
                tickers,
                start=start_date,
                end=end_date,
                progress=True,
                session=self.session,
                group_by="ticker",  # Ensure data is grouped by ticker
                repair=True,
            )

            if data is None or data.empty:
                logger.warning("No data found for the given tickers and date range.")
                return pd.DataFrame()

            # If multiple tickers are downloaded, the columns will be MultiIndex
            if len(tickers) > 1:
                data = (
                    data.stack(level=0)
                    .reset_index()
                    .rename(columns={"level_1": "Ticker"})
                )
            else:
                data["Ticker"] = tickers[0]  # Add ticker column for single-ticker data

            logger.info("Data download completed successfully.")
            return data

        except Exception as e:
            logger.error(f"Error downloading data: {e}")
            return pd.DataFrame()

    def clean(
        self, df_to_clean: pd.DataFrame, outlier_identifier: OutlierIdentifier
    ) -> pd.DataFrame:
        """
        Cleans stock data by handling outliers and interpolating missing values.
        """
        if df_to_clean.empty:
            logger.warning("DataFrame is empty, nothing to clean.")
            return df_to_clean

        logger.info("Cleaning data...")
        outlier_mask = outlier_identifier.quantile(df_to_clean)
        df_cleaned = outlier_identifier.interpolate(df_to_clean, outlier_mask)

        logger.info("Data cleaning completed.")
        return df_cleaned
