import logging

from stock_data_downloader.config.download_arg_parser import parse_arguments
from stock_data_downloader.config.logging_config import setup_logging
from stock_data_downloader.data_processing.data_downloader import download_stock_data
from stock_data_downloader.data_provider.DataProviderFactory import DataProviderFactory


def main():
    args = parse_arguments()
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting the stock data downloader.")

    # Parse command-line arguments

    logger.info(f"Arguments parsed: {args}")

    data_provider_factory = DataProviderFactory()
    data_provider = data_provider_factory.create(args.data_provider, args.secret_file)

    # Download and process stock data
    try:
        download_stock_data(args, data_provider)
        logger.info("Stock data download and processing completed successfully.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()
