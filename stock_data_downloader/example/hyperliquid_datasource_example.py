import asyncio
import threading
from typing import Any, List

from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource
from stock_data_downloader.models import HyperliquidDataSourceConfig


async def data_callback(kind: str, payload: List[dict[str, Any]]):
    """Callback for real-time data updates.
    
    Args:
        kind: The type of update (typically "price_update" for market data)
        payload: List of market data dictionaries, each containing:
            - ticker: str - The ticker symbol
            - timestamp: str - ISO format timestamp
            - open: float - Opening price
            - high: float - Highest price
            - low: float - Lowest price
            - close: float - Closing price
            - volume: float - Trading volume
    """
    if kind == "price_update":
        for data in payload:
            print(f"Price update: {data['ticker']} - {data['close']} at {data['timestamp']}")


async def main():
    # Define configuration
    config = HyperliquidDataSourceConfig(
        source_type="hyperliquid",
        network="testnet",
        tickers=['BTC', 'ETH'],
        interval='1m',
        api_config={}
    )

    # Initialize HyperliquidDataSource
    data_source = HyperliquidDataSource(
        config=config.api_config,
        network=config.network,
        tickers=config.tickers,
        interval=config.interval
    )

    # Subscribe to real-time data
    print("Subscribing to real-time data...")
    await data_source.subscribe_realtime_data(data_callback)

    # Run for 30 seconds to receive updates
    print("Receiving data for 30 seconds...")
    await asyncio.sleep(30)

    # Clean up
    print("Unsubscribing from real-time data...")
    await data_source.unsubscribe_realtime_data()
    print("Threads still alive:", threading.enumerate())
    print("Shutting down...")


# Run the async main function
if __name__ == "__main__":
    asyncio.run(main())