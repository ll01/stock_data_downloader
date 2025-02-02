import logging
from typing import List
import pandas as pd
import requests
from datetime import datetime

from stock_data_downloader.data_provider.DataProvider import DataProvider
from stock_data_downloader.data_provider.OutlierIdentifier import OutlierIdentifier

logger = logging.getLogger(__name__)


class BinanceDataProvider(DataProvider):
    def __init__(self, api_base_url: str = "https://api.binance.com/api/v3"):
        """
        Initialize the Binance data provider.
        :param api_base_url: Base URL for the Binance API (default is the public API).
        """
        self.api_base_url = api_base_url

    def download_ticker_data(
        self, tickers: List[str], start_date: str, end_date: str, interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Downloads historical cryptocurrency data from Binance for the given tickers and date range.
        :param tickers: List of trading pairs (e.g., ["BTCUSDT", "ETHUSDT"]).
        :param start_date: Start date in the format "YYYY-MM-DD".
        :param end_date: End date in the format "YYYY-MM-DD".
        :param interval: Time interval for the data (e.g., "1m", "1h", "1d").
        :return: DataFrame containing the historical data.
        """
        logger.info(
            f"Downloading data for {len(tickers)} tickers from {start_date} to {end_date}..."
        )

        all_data = []
        for ticker in tickers:
            try:
                # Convert start and end dates to timestamps
                start_timestamp = int(
                    datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000
                )
                end_timestamp = int(
                    datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000
                )

                # Fetch historical klines (candlestick data)
                url = f"{self.api_base_url}/klines"
                params = {
                    "symbol": ticker,
                    "interval": interval,
                    "startTime": start_timestamp,
                    "endTime": end_timestamp,
                    "limit": 1000,  # Maximum number of data points per request
                }

                response = requests.get(url, params=params)
                response.raise_for_status()  # Raise an error for bad responses
                data = response.json()

                # Convert the data to a DataFrame
                columns = [
                    "Open Time",
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                    "Close Time",
                    "Quote Asset Volume",
                    "Number of Trades",
                    "Taker Buy Base Asset Volume",
                    "Taker Buy Quote Asset Volume",
                    "Ignore",
                ]
                df = pd.DataFrame(data, columns=columns)

                # Convert timestamps to readable dates
                df["Open Time"] = pd.to_datetime(df["Open Time"], unit="ms")
                df["Close Time"] = pd.to_datetime(df["Close Time"], unit="ms")

                # Add ticker column
                df["Ticker"] = ticker

                # Append to the list of all data
                all_data.append(df)

            except Exception as e:
                logger.error(f"Error downloading data for {ticker}: {e}")

        if not all_data:
            logger.warning("No data found for the given tickers and date range.")
            return pd.DataFrame()

        # Combine all ticker data into a single DataFrame
        combined_df = pd.concat(all_data, ignore_index=True)
        logger.info("Data download completed successfully.")
        return combined_df

    def clean(
        self, df_to_clean: pd.DataFrame, outlier_identifier: OutlierIdentifier
    ) -> pd.DataFrame:
        """
        Cleans cryptocurrency data by handling outliers and interpolating missing values.
        """
        if df_to_clean.empty:
            logger.warning("DataFrame is empty, nothing to clean.")
            return df_to_clean

        logger.info("Cleaning data...")
        outlier_mask = outlier_identifier.quantile(df_to_clean)
        df_cleaned = outlier_identifier.interpolate(df_to_clean, outlier_mask)

        logger.info("Data cleaning completed.")
        return df_cleaned
