import asyncio
import logging

from stock_data_downloader.config.logging_config import setup_logging
from stock_data_downloader.config.sim_arg_parser import parse_arguments
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import simulate_prices
from stock_data_downloader.etl.parquet_etl import load_stock_stats, save_to_parquet
from stock_data_downloader.websocket_server.server import start_websocket_server


def generate_basic_start_prices(
    starting_price: float, stats: dict[str, TickerStats]
) -> dict[str, float]:
    """Generates basic starting prices for each ticker."""
    return {ticker: starting_price for ticker, _ in stats.items()}


async def main():
    args = parse_arguments()
    setup_logging(args.log_level)
    logging.info("Starting simulation...")

    stats = load_stock_stats(args.sim_data_file)
    start_prices = generate_basic_start_prices(args.start_price, stats)
    simulated_prices = simulate_prices(
        stats, start_prices, args.time_steps, args.interval, args.seed
    )

    if simulated_prices:  # Check if simulation was successful
        if args.output_format == "parquet":
            save_to_parquet(simulated_prices, args.output_file)
        elif args.output_format == "websocket":
            await start_websocket_server(
                args.seed,
                simulated_prices,
                start_prices,
                stats,
                args.interval,
                args.websocket_uri,
                args.realtime,
                args.time_steps
            )


if __name__ == "__main__":
    asyncio.run(main())
