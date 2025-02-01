import logging
import time
from datetime import datetime
from typing import List

import pandas as pd
import requests

from DataProvider import DataProvider
from OutlierIdentifier import OutlierIdentifier

logger = logging.getLogger(__name__)

class AlphaVantageDataProvider(DataProvider):
    BASE_URL = "https://www.alphavantage.co/query"
    
    def __init__(self, api_key: str):
        """
        Initialize the AlphaVantageDataProvider with an API key.
        """
        self.api_key = api_key

    def download_ticker_data(
        self, tickers: List[str], start_date: datetime, end_date: datetime,
        requests_per_minute: int
    ) -> pd.DataFrame:
        """
        Downloads historical stock data from Alpha Vantage.

        Args:
            tickers (List[str]): List of stock tickers.
            start_date (datetime): Start date for Ndata retrieval.
            end_date (datetime): End date for data retrieval.
            requests_per_minute (int): Max API requests per minute.

        Returns:
            pd.DataFrame: Combined stock data for all tickers.
        """
        all_data = []
        interval = 60 / requests_per_minute  # Ensures we respect the rate limit

        for ticker in tickers:
            print(f"Downloading {ticker} data from {start_date} to {end_date}...")

            params = {
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": ticker,
                "apikey": self.api_key,
                "outputsize": "full",
                "datatype": "json",
            }

            try:
                response = requests.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

                if "Time Series (Daily)" not in data:
                    print(f"Warning: No data found for {ticker}")
                    continue

                df = pd.DataFrame.from_dict(
                    data["Time Series (Daily)"], orient="index"
                ).astype(float)

                df.index = pd.to_datetime(df.index)  # Convert index to datetime
                df = df.rename(columns={
                    "1. open": "open",
                    "2. high": "high",
                    "3. low": "low",
                    "4. close": "close",
                    "5. adjusted close": "adj_close",
                    "6. volume": "volume"
                })

                df["ticker"] = ticker  # Add ticker column for reference

                # Filter dates within the given range
                df = df[(df.index >= start_date) & (df.index <= end_date)]
                all_data.append(df)

                time.sleep(interval)  # Respect API rate limit

            except requests.RequestException as e:
                print(f"Error downloading {ticker}: {e}")

        if all_data:
            df_final = pd.concat(all_data)
            df_final.reset_index(inplace=True)  # Reset index to move 'Date' to a column
            df_final.rename(columns={"index": "date"}, inplace=True)
            return df_final
        else:
            return pd.DataFrame()  # Return empty DataFrame if no data was retrieved

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