from abc import ABC, abstractmethod
from typing import List

import pandas as pd

from stock_data_downloader.data_provider.OutlierIdentifier import OutlierIdentifier


class DataProvider(ABC):
    @abstractmethod
    def download_ticker_data(
        self, tickers: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        pass
    
    @abstractmethod
    def clean(
        self, df_to_clean: pd.DataFrame, outlier_identifier: OutlierIdentifier 
    ) -> pd.DataFrame:
        pass
