import logging

from stock_data_downloader.data_provider.DataProvider import DataProvider
from stock_data_downloader.data_provider.YahooFinanceDataProvider import YahooFinanceDataProvider




class DataProviderFactory:
    def create(self, data_provider_name: str) -> DataProvider:
        """
        Factory method to create a DataProvider instance based on the provider name.
        """
        logger = logging.getLogger(__name__)

        if data_provider_name == "yahoo":
            logger.info("Initializing YahooFinanceDataProvider.")
            return YahooFinanceDataProvider(requests_per_minute=5)  # Adjust rate limit as needed
        elif data_provider_name == "alphavantage":
            logger.info("AlphaVantageDataProvider is not implemented yet.")
            raise NotImplementedError("AlphaVantageDataProvider is not implemented.")
        else:
            error_msg = f"Unsupported data provider: {data_provider_name}"
            logger.error(error_msg)
            raise ValueError(error_msg)