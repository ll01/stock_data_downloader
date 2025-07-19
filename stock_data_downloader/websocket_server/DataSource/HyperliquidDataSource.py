import asyncio
from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Dict, List, Optional, Tuple, Union, Awaitable
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.types import CandleSubscription
import logging
from stock_data_downloader.models import TickerData
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)
from collections.abc import Callable
from hyperliquid.websocket_manager import WebsocketManager

from stock_data_downloader.websocket_server.thread_cancel_helper import (
    _async_raise,
    find_threads_by_name,
)

logger = logging.getLogger(__name__)


class HyperliquidDataSource(DataSourceInterface):
    def __init__(
        self,
        config: Dict,
        network: str = "mainnet",
        tickers: List[str] = [],
        interval: str = "1m",
    ):
        super().__init__(tickers, interval)
        self.config = config
        self.network = network
        self.base_url = (
            constants.TESTNET_API_URL
            if network == "testnet"
            else constants.MAINNET_API_URL
        )
        self._info = Info(base_url=self.base_url)
        self._callback: Optional[Callable[[Any], Awaitable[None]]] = None
        self.current_prices: Dict[str, float] = {}
        self.interval = interval
        self._subscriptions: List[Tuple[CandleSubscription, int]] = []
        self._ws = WebsocketManager(self.base_url)
        self._ws.daemon = True
        self._ws.ping_sender.daemon = True

    async def get_historical_data(
        self, tickers: List[str] = [], interval: str = ""
    ) -> List[TickerData]:
        """Fetch historical OHLCV data and yield it as a single batch."""
        tickers = tickers or self.tickers
        interval = interval or self.interval
        all_ticker_data = []

        for ticker in tickers:
            try:
                end_time = datetime.now(timezone.utc)
                # Fetch a reasonable amount of recent data for priming
                start_time = end_time - timedelta(days=1)
                start_timestamp = int(start_time.timestamp() * 1000)
                end_timestamp = int(end_time.timestamp() * 1000)

                ohlcv = self._info.candles_snapshot(
                    ticker, interval, start_timestamp, end_timestamp
                )

                for entry in ohlcv:
                    all_ticker_data.append(self._map_candle_message(entry))

            except Exception as e:
                logger.error(f"Error fetching historical data for {ticker}: {e}")
            finally:
                # Respect potential rate limits
                await asyncio.sleep(0.25)
        return all_ticker_data

    async def subscribe_realtime_data(self, callback: Callable[[str, Any], Awaitable[None]]):
        """
        Subscribe to real-time price updates via WebSocket.

        This method establishes a connection to the Hyperliquid WebSocket API
        and sets up subscriptions for the specified tickers. It uses the
        standardized callback mechanism to ensure consistent behavior with
        other data sources like BacktestDataSource.

        Args:
            callback: Function to call when new data is available.
                     The callback will receive data in a standardized format.
        """
        self._callback = callback

        # Start WebSocket connection with retry logic
        await self._connect_with_retry()

        # Ensure threads are properly configured
        for thread in [self._ws.ping_sender]:
            if thread and isinstance(thread, threading.Thread) and thread.is_alive():
                thread.daemon = True

        # Subscribe to each ticker
        for ticker in self.tickers:
            subscription: CandleSubscription = {
                "type": "candle",
                "coin": ticker,
                "interval": self.interval,
            }
            try:
                sub_id = self._ws.subscribe(
                    subscription, callback=self._handle_ws_message
                )
                self._subscriptions.append((subscription, sub_id))
                logger.info(f"Successfully subscribed to {ticker} candle data")
            except Exception as e:
                logger.error(f"Failed to subscribe to {ticker}: {e}")
                # Continue with other tickers even if one fails

    async def unsubscribe_realtime_data(self):
        """
        Unsubscribe from real-time data.

        This method cleans up all WebSocket subscriptions and resources,
        with improved error handling to ensure proper cleanup even if
        some operations fail.
        """
        try:
            # 1) Unsubscribe all WS subscriptions
            for sub, sub_id in self._subscriptions:
                try:
                    self._info.unsubscribe(sub, sub_id)
                except Exception as e:
                    logger.warning(f"Error unsubscribing from {sub}: {e}")
            self._subscriptions.clear()

            # 2) Stop the ping loop and the WebSocketApp
            try:
                if hasattr(self._ws, "stop"):
                    self._ws.stop()
                if hasattr(self._ws, "ws"):
                    if hasattr(self._ws.ws, "close"):
                        self._ws.ws.close()
                    if hasattr(self._ws.ws, "keep_running"):
                        self._ws.ws.keep_running = False
            except Exception as e:
                logger.warning(f"Error stopping WebSocket: {e}")

            # 3) Wait for ping_sender to fully exit
            try:
                if (
                    hasattr(self._ws, "ping_sender")
                    and self._ws.ping_sender
                    and self._ws.ping_sender.is_alive()
                ):
                    self._ws.ping_sender.join(
                        timeout=2.0
                    )  # Add timeout to avoid hanging
            except Exception as e:
                logger.warning(f"Error waiting for ping sender thread: {e}")

            # 4) Wait for the WebsocketManager thread to finish
            try:
                if self._ws.is_alive():
                    self._ws.join(timeout=2.0)  # Add timeout to avoid hanging
            except Exception as e:
                logger.warning(f"Error waiting for WebSocket manager thread: {e}")

            # 5) Clean up any remaining threads
            try:
                # Find and terminate any lingering WebsocketManager threads
                ws_threads = [
                    t for t in threading.enumerate() if isinstance(t, WebsocketManager)
                ]
                for t in ws_threads:
                    try:
                        _async_raise(t.ident, SystemExit)
                    except Exception as e:
                        logger.warning(f"Error terminating WebSocket thread: {e}")

                # Find and terminate any lingering ping threads
                ping_threads = find_threads_by_name("send_ping")
                for t in ping_threads:
                    try:
                        _async_raise(t.ident, SystemExit)
                    except Exception as e:
                        logger.warning(f"Error terminating ping thread: {e}")
            except Exception as e:
                logger.warning(f"Error cleaning up threads: {e}")

            # 6) Clean up the WebSocket manager
            try:
                del self._ws
            except Exception as e:
                logger.warning(f"Error deleting WebSocket manager: {e}")

        except Exception as e:
            logger.error(f"Error during unsubscribe_realtime_data: {e}", exc_info=True)
        finally:
            # Always clear the callback reference
            self._callback = None
            logger.info("Unsubscribed from Hyperliquid real-time data")

    def _map_candle_message(self, msg: dict) -> TickerData:
        """
        Map a raw WS candle message with short keys to a full-label dict.

        Input example:
        {
            't': 1746192900000,
            'T': 1746192959999,
            's': 'BTC',
            'c': '1m',
            'o': '96899.0',
            'h': '96899.0',
            'l': '96899.0',|
            'c': '96899.0',
            'v': '0.01',
            'n': 1
        }

        Output:
        {
            'timestamp': '2025-07-01T12:15:59.999000+00:00',
            'ticker': 'BTC',
            'open': 96899.0,
            'high': 96899.0,
            'low': 96899.0,
            'close': 96899.0,
            'volume': 0.01,
        }
        """
        return TickerData(
            ticker=msg["s"],
            timestamp=datetime.fromtimestamp(msg["T"] / 1000, timezone.utc).isoformat(),
            open=float(msg["o"]),
            high=float(msg["h"]),
            low=float(msg["l"]),
            close=float(msg["c"]),
            volume=float(msg["v"]),
        )

    def _handle_ws_message(self, message: Dict[str, Any]):
        """
        Process incoming WebSocket messages and forward to user callback.

        This method processes raw WebSocket messages from Hyperliquid,
        transforms them into the standardized format, and forwards them
        to the callback using the _notify_callback method from the parent class.

        Args:
            message: Raw WebSocket message from Hyperliquid
        """
        try:
            candle_data = message.get("data")
            if not candle_data or message.get("channel") != "candle":
                return

            # Normalize the data to ensure consistent format with other data sources
            normalized_data = self._map_candle_message(candle_data)

            self.current_prices[normalized_data.ticker] = normalized_data.close
                

            # Use the callback with the normalized data
            if self._callback:
                # Create async task to handle the async callback
                asyncio.create_task(self._notify_callback([normalized_data]))

        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}", exc_info=True)

    async def _connect_with_retry(self):
        """
        Connect to Hyperliquid WebSocket with exponential backoff retry logic.

        This method attempts to establish a connection to the Hyperliquid WebSocket API
        with exponential backoff retry logic to handle temporary connection issues.
        """
        retry_delay = 1.0
        max_retry_delay = 60.0
        max_retries = 5
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Start the WebSocket connection
                self._ws.start()
                logger.info(
                    f"Successfully connected to Hyperliquid WebSocket API ({self.network})"
                )
                return
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(
                        f"Failed to connect to Hyperliquid WebSocket API after {max_retries} attempts: {e}"
                    )
                    raise

                logger.warning(
                    f"Connection attempt {retry_count} failed: {e}. Retrying in {retry_delay:.1f}s..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

                # Recreate WebSocket manager for next attempt
                self._ws = WebsocketManager(self.base_url)
                self._ws.daemon = True
                self._ws.ping_sender.daemon = True

    async def reset(self):
        """
        Reset data source.

        This method resets the data source by unsubscribing from the current
        WebSocket connection, recreating the WebSocket manager, and reconnecting
        if there was an active callback.
        """
        old_callback = self._callback
        await self.unsubscribe_realtime_data()

        # Recreate WebSocket manager
        self._ws = WebsocketManager(self.base_url)
        self._ws.daemon = True
        self._ws.ping_sender.daemon = True

        # Reconnect if we had a callback
        if old_callback:
            await self.subscribe_realtime_data(old_callback)

        self._info = Info(base_url=self.base_url)
        logger.info("Hyperliquid data source reset complete.")
