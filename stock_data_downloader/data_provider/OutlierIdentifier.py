from typing import Union
import pandas as pd


class OutlierIdentifier:
    __outlier_columns__ = ["Open", "High", "Low", "Close", "Volume"]
    
    def quantile(
        self,
        data: pd.DataFrame,
        lower_quantile: float = 0.25,
        upper_quantile: float = 0.75,
    ) -> Union[pd.Series, pd.DataFrame]:
        changes = data[self.__outlier_columns__].pct_change()

        Q1 = changes.quantile(lower_quantile)
        Q3 = changes.quantile(upper_quantile)
        IQR = Q3 - Q1

        # Define outliers as values outside 1.5 * IQR from Q1 or Q3
        outliers = (changes < (Q1 - 1.5 * IQR)) | (changes > (Q3 + 1.5 * IQR))
        return outliers

    def z_score(
        self, data: pd.DataFrame, outlier_z_score: float = 2
    ) -> Union[pd.Series, pd.DataFrame]:
        changes = data[self.__outlier_columns__].pct_change()
        mean = changes.mean()
        # ddof of 1 because its a sample of a population
        sd = changes.std(ddof=1).dropna()
        z_scores = (changes - mean) / sd
        outliers = z_scores.abs() > outlier_z_score
        return outliers

    def interpolate(
        self, data: pd.DataFrame, outlier_mask: Union[pd.Series, pd.DataFrame]
    ):
        cleaned_data = data[self.__outlier_columns__].copy()
        cleaned_data[outlier_mask] = None
        cleaned_data = cleaned_data.interpolate(method="linear")
        
        cleaned_data["Ticker"] = data["Ticker"]
        cleaned_data["Date"] = data["Date"]
        # reorder the columns to match the original DataFrame
        cleaned_data = cleaned_data[['Date', 'Ticker'] + self.__outlier_columns__]
    
        return cleaned_data
