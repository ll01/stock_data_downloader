from argparse import Namespace
import logging
from pathlib import Path

from tqdm import tqdm

from stock_data_downloader.data_provider.DataProvider import DataProvider
from stock_data_downloader.data_provider.OutlierIdentifier import OutlierIdentifier
from stock_data_downloader.etl.csv_etl import (
    cleanup_csv_files,
    save_data_to_csv,
    zip_csv_file,
)
from stock_data_downloader.etl.ticker_util import load_tickers_from_file
from tqdm.contrib.logging import logging_redirect_tqdm


logger = logging.getLogger(__name__)


def download_stock_data(args: Namespace, data_provider: DataProvider):
    logger = logging.getLogger(__name__)
    chunk_size = args.chunk_size
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
    logger.info(f"CSV files zipped to {args.zip_file}")
    if not args.keep_csv:
        cleanup_csv_files(csv_files)
        logger.info(f"Removed {len(csv_files)} intermediate CSV files")
    else:
        logger.info("Intermediate CSV files retained as --keep-csv was specified.")
