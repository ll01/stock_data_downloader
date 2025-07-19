import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Awaitable

# Import CCXT Pro for WebSocket support
import ccxt

from stock_data_downloader.models import CCXTDataSourceConfig, TickerData
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)


class CCXTDataSource(DataSourceInterface):
    def __init__(self, cfg: CCXTDataSourceConfig):
        super().__init__(tickers=cfg.tickers, interval=cfg.interval)
        self.cfg = cfg

        exchange_class = getattr(ccxt, cfg.exchange_id)
        self._exchange = exchange_class(
            {
                "apiKey": cfg.credentials.get("api_key", ""),
                "secret": cfg.credentials.get("secret", ""),
                "password": cfg.credentials.get("password"),
                "sandbox": cfg.sandbox,
                "enableRateLimit": True,
                "options": cfg.options or {},
            }
        )

    async def get_historical_data(
        self, tickers: List[str] = [], interval: str = ""
    ) -> List[TickerData]:
        """
        Fetch historical OHLCV data from the exchange.

        Args:
            tickers: List of ticker symbols (e.g., ['BTC/USD', 'ETH/USD'])
            interval: Timeframe for OHLCV data (e.g., '1m', '1h')

        Returns:
            Dict[str, List[Dict[str, float]]]: Historical OHLCV data per ticker.
        """
        tickers = tickers or self.tickers
        historical_data = []
        subscriptions = [[ticker, interval] for ticker in tickers]

        for ticker in tickers:
            try:
                ohlcv = await self._exchange.fetch_ohlcv(subscriptions)  # type: ignore
                for entry in ohlcv:
                    historical_data.append(
                        TickerData(
                            ticker=ticker,
                            timestamp=entry[0],
                            open=entry[1],
                            high=entry[2],
                            low=entry[3],
                            close=entry[4],
                            volume=entry[5],
                        )
                    )
            except Exception as e:
                print(f"Error fetching historical data for {ticker}: {e}")

        return historical_data

    async def subscribe_realtime_data(self, callback: Callable[[str, Any], Awaitable[None]]):
        """
        Subscribe to real-time data via WebSocket and trigger the callback on updates.
        """
        if self._ws_task and not self._ws_task.done():
            print("Existing WebSocket task found, unsubscribing first.")
            await self.unsubscribe_realtime_data()

        self._callback = callback
        self._ws_task = asyncio.create_task(self._start_websocket_stream())

    async def unsubscribe_realtime_data(self):
        """
        Unsubscribe from real-time data streams by stopping the WebSocket task.
        """
        if self._ws_task and not self._ws_task.done():
            print("Cancelling WebSocket task...")
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                print("WebSocket task cancelled.")
            finally:
                self._ws_task = None
                self._callback = None
        else:
            print("No active WebSocket task to cancel.")

    async def _start_websocket_stream(self):
        """
        Internal task to connect to the exchange’s WebSocket and stream real-time data.
        """
        try:
            while True:
                for ticker in self.tickers:
                    try:
                        # Subscribe to ticker updates (e.g., price, order book, trades)
                        # TODO: if ccxt.base.errors.NotSupported error fall back to polling
                        # TODO: why is
                        await self._exchange.watch_ohlcv(ticker)  # type: ignore

                        # Get the latest ticker data and notify callback
                        ticker_data = self._exchange.store["ticker"][ticker]
                        if ticker_data:
                            payload = {
                                "ticker": ticker,
                                "open": ticker_data.get("open"),
                                "high": ticker_data.get("high"),
                                "low": ticker_data.get("low"),
                                "close": ticker_data.get("close"),
                                "volume": ticker_data.get("volume"),
                                "timestamp": ticker_data.get("timestamp"),
                            }
                            await self._notify_callback(payload)

                    except Exception as e:
                        print(f"Error in WebSocket stream for {ticker}: {e}")
                        await asyncio.sleep(5)  # Reconnect after delay

                await asyncio.sleep(1)  # Prevent overwhelming the loop

        except asyncio.CancelledError:
            print("WebSocket stream task received cancellation signal.")
            raise
        except Exception as e:
            print(f"An error occurred in the WebSocket stream: {e}")
        finally:
            print("WebSocket stream task finished.")

    async def reset(self):
        """
        Reset the data source by unsubscribing and reinitializing the exchange.
        """
        await self.unsubscribe_realtime_data()
        print("CCXT data source has been reset.")
