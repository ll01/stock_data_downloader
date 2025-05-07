import asyncio
import threading
from typing import Any

from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource


async def main():
    # Define tickers (Hyperliquid uses perpetual contract symbols like 'BTC/USD:USD')
    tickers = ['BTC', 'ETH']

    # Initialize CCXTDataSource for Hyperliquid
    data_source = HyperliquidDataSource(
        # exchange_id='hyperliquid',  # Ensure CCXT supports this exchange ID
        config={
            'api_key': 'key',
            'api_secret': 'secret',
        },
        tickers=tickers,
        interval='1m',  # OHLCV interval
        network="mainnet"
    )
    # markets = data_source._exchange.load_markets()
    # print(f"market format {markets[0]}")

    # Define a callback for real-time updates
    def callback( payload: Any):
        print(f"Received update: {payload}")

    # Subscribe to real-time data
    await data_source.subscribe_realtime_data(callback)

    # Run for 60 seconds to receive updates
    await asyncio.sleep(10)

    # Clean up
    await data_source.unsubscribe_realtime_data()
    print("Threads still alive:", threading.enumerate())
    print("shutting down ...")
    # os._exit(0) 

# Run the async main function
asyncio.run(main())