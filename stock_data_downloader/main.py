import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from etl.csv_etl import cleanup_csv_files, save_data_to_csv, zip_csv_file
from stock_data_downloader.data_provider.DataProvider import DataProvider
from stock_data_downloader.data_provider.DataProviderFactory import DataProviderFactory
from stock_data_downloader.data_provider.OutlierIdentifier import OutlierIdentifier


def setup_logging():
    """
    Set up logging configuration for the application.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),  # Log to console
            logging.FileHandler("app.log", encoding="utf-8"),  # Log to a file
        ],
    )
    logging.info("Logging configured successfully.")


def load_tickers_from_file(file_path):
    """Load tickers from a file."""
    with open(file_path, "r") as file:
        tickers = [line.strip() for line in file if line.strip()]
    return tickers


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
        help="Start date for the data (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.today().strftime("%Y-%m-%d"),
        help="End date for the data (default: today)",
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
    return parser.parse_args()


def download_stock_data(args: argparse.Namespace, data_provider: DataProvider):
    logger = logging.getLogger(__name__)
    chunk_size = 10
    tickers = load_tickers_from_file(args.ticker_file)
    chunks = [tickers[i : i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    outlier_identifier = OutlierIdentifier()
    csv_files = []
    with logging_redirect_tqdm():
        for i, chunk in tqdm(
            enumerate(chunks), total=len(chunks), desc="Processing chunks"
        ):
            try:
                # Fetch data for the current chunk
                data = data_provider.download_ticker_data(
                    chunk, args.start_date, args.end_date
                )
                if data.empty:
                    logger.warning(f"No data found for chunk: {chunk}")
                    continue

                # Clean the data
                cleaned_data = data_provider.clean(data, outlier_identifier)

                # Save the cleaned data to a CSV file
                temp = Path(args.csv_file)
                csv_chunk_name = f"{temp.stem}_part{i}{temp.suffix}"
                save_data_to_csv(cleaned_data, csv_chunk_name)
                logger.info(f"Saved cleaned data to {csv_chunk_name}")
                csv_files.append(csv_chunk_name)
            except Exception as e:
                logger.error(f"Error processing chunk {chunk}: {e.with_traceback}")
                continue
    zip_csv_file(csv_files, args.zip_file)
    logger.info("Adding to zip file")
    cleanup_csv_files(csv_files)
    logger.info(f"Removing {len(csv_files)} CSV files")


def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting the stock data downloader.")

    # Parse command-line arguments
    args = parse_arguments()
    logger.info(f"Arguments parsed: {args}")

    data_provider_factory = DataProviderFactory()
    data_provider = data_provider_factory.create(args.data_provider)

    # Download and process stock data
    try:
        download_stock_data(args, data_provider)
        logger.info("Stock data download and processing completed successfully.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()
