import argparse
from datetime import datetime


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch OHLC data for a list of tickers and save it to a zipped CSV file."
    )
    parser.add_argument(
        "--ticker-file",
        type=str,
        default="tickers.txt",
        help="Path to the file containing tickers (default: tickers.txt)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2020-01-01",
        help="Start date for the data in YYYY-MM-DD format (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.today().strftime("%Y-%m-%d"),
        help="End date for the data in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--csv-file",
        type=str,
        default="ohlc_data.csv",
        help="Path to the output CSV file (default: ohlc_data.csv)",
    )
    parser.add_argument(
        "--zip-file",
        type=str,
        default="ohlc_data.zip",
        help="Path to the output ZIP file (default: ohlc_data.zip)",
    )
    parser.add_argument(
        "--data-provider",
        type=str,
        default="yahoo",
        choices=["yahoo", "alphavantage"],  # Restrict to supported providers
        help="Data provider to use (default: yahoo)",
    )
    parser.add_argument(
        "--secret-file",
        type=str,
        default="secrets.json",
        help="Path to the file containing API keys or secrets (default: secrets.json)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=10,
        help="Number of tickers to process in each chunk (default: 10)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    parser.add_argument(
        "--keep-csv",
        action="store_true",
        help="Keep intermediate CSV files after zipping (default: False)",
    )
    return parser.parse_args()