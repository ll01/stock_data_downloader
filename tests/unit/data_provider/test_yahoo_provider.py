import pandas as pd
import pytest
from pathlib import Path
from stock_data_downloader.data_provider.YahooFinanceDataProvider import YahooFinanceDataProvider

def test_download_ticker_data_single_ticker(monkeypatch, tmp_path: Path):
    # Arrange: stub yfinance.download to return a simple DataFrame
    def fake_download(tickers, start, end, progress, session, group_by, repair):
        return pd.DataFrame({
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [1000],
        })

    monkeypatch.setattr(
        "stock_data_downloader.data_provider.YahooFinanceDataProvider.yf.download",
        fake_download,
    )

    provider = YahooFinanceDataProvider(requests_per_minute=10, tz_custom_cache_location=str(tmp_path))

    # Act
    df = provider.download_ticker_data(["AAPL"], "2020-01-01", "2020-01-02")

    # Assert
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "Ticker" in df.columns

def test_clean_uses_outlier_identifier(tmp_path: Path):
    # Arrange: simple DataFrame with an obvious outlier at index 1
    df = pd.DataFrame({"Close": [1.0, 1000.0, 2.0]})

    class DummyOutlierIdentifier:
        def quantile(self, df_to_check):
            # Mark values > 100 as outliers
            return df_to_check["Close"] > 100

        def interpolate(self, df_to_clean, mask):
            # Replace outliers with the median of non-outlier values
            clean = df_to_clean.copy()
            median_val = df_to_clean.loc[~mask, "Close"].median()
            clean.loc[mask, "Close"] = median_val
            return clean

    provider = YahooFinanceDataProvider(requests_per_minute=10, tz_custom_cache_location=str(tmp_path))
    outlier_identifier = DummyOutlierIdentifier()

    # Act
    cleaned = provider.clean(df, outlier_identifier)

    # Assert: outlier at index 1 replaced by median of [1.0, 2.0] => 1.5
    assert cleaned.loc[1, "Close"] == pytest.approx(1.5)