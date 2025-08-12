import asyncio
import threading
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, Awaitable

from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.types import CandleSubscription
from hyperliquid.websocket_manager import WebsocketManager

from stock_data_downloader.models import TickerData
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.websocket_server.thread_cancel_helper import _async_raise, find_threads_by_name

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
        self.base_url = constants.TESTNET_API_URL if network == "testnet" else constants.MAINNET_API_URL
        self.interval = interval
        self._info = Info(base_url=self.base_url)
        self._ws = self._create_ws_manager()
        self._subscriptions: List[Tuple[CandleSubscription, int]] = []

    def _create_ws_manager(self) -> WebsocketManager:
        ws = WebsocketManager(self.base_url)
        ws.daemon = True
        ws.ping_sender.daemon = True
        return ws

    def _map_candle_message(self, msg: Dict[str, Any]) -> TickerData:
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
        """Process incoming websocket message and deliver to callback safely (supports async)."""
        if message.get("channel") != "candle":
            return

        candle_data = message.get("data")
        if not candle_data:
            return

        try:
            normalized = self._map_candle_message(candle_data)
            self.current_prices[normalized.ticker] = normalized.close

            async def _safe_async_call():
                try:
                    await self._notify_callback("price_update", [normalized])
                except Exception:
                    logger.exception("Unhandled exception in async data callback")

            if asyncio.iscoroutinefunction(self._callback) or asyncio.iscoroutinefunction(self._notify_callback):
                try:
                    asyncio.create_task(_safe_async_call())
                except RuntimeError:
                    # No running loop — run synchronously in fresh loop
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self._notify_callback("price_update", [normalized]))
                    loop.close()
            else:
                try:
                    # if sync callback, call directly
                    if callable(self._notify_callback):
                        result = self._notify_callback("price_update", [normalized])
                        # swallow coroutine if accidentally returned without awaiting
                        if asyncio.iscoroutine(result):
                            try:
                                asyncio.create_task(result)
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                loop.run_until_complete(result)
                                loop.close()
                except Exception:
                    logger.exception("Unhandled exception in sync data callback")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}", exc_info=True)

    async def _connect_with_retry(self, retries: int = 5, base_delay: float = 1.0):
        for attempt in range(retries):
            try:
                self._ws.start()
                logger.info(f"Connected to Hyperliquid WebSocket ({self.network})")
                return
            except Exception as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}, retrying in {delay}s")
                await asyncio.sleep(delay)

        raise ConnectionError(f"Failed to connect to Hyperliquid WebSocket after {retries} attempts.")

    async def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> List[TickerData]:
        tickers = tickers or self.tickers
        interval = interval or self.interval
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=1)
        start_ts, end_ts = int(start_time.timestamp() * 1000), int(end_time.timestamp() * 1000)

        all_data = []
        for ticker in tickers:
            try:
                candles = self._info.candles_snapshot(ticker, interval, start_ts, end_ts)
                all_data.extend(self._map_candle_message(c) for c in candles)
            except Exception as e:
                logger.error(f"Error fetching historical data for {ticker}: {e}")
            await asyncio.sleep(0.25)  # Respect rate limits
        return all_data

    async def subscribe_realtime_data(self, callback: Callable[[str, Any], Awaitable[None]]):
        self._callback = callback
        await self._connect_with_retry()

        for ticker in self.tickers:
            subscription: CandleSubscription = {
                "type": "candle",
                "coin": ticker,
                "interval": self.interval,
            }
            try:
                sub_id = self._ws.subscribe(subscription, callback=self._handle_ws_message)
                self._subscriptions.append((subscription, sub_id))
                logger.info(f"Subscribed to {ticker}")
            except Exception as e:
                logger.error(f"Failed to subscribe to {ticker}: {e}")

    async def unsubscribe_realtime_data(self):
        for sub, sub_id in self._subscriptions:
            try:
                self._info.unsubscribe(sub, sub_id)
            except Exception as e:
                logger.warning(f"Error unsubscribing {sub}: {e}")
        self._subscriptions.clear()

        try:
            self._ws.stop()
            self._ws.ws.close()
            self._ws.ws.keep_running = False
        except Exception as e:
            logger.warning(f"Error stopping WebSocket: {e}")

        try:
            if self._ws.ping_sender.is_alive():
                self._ws.ping_sender.join(timeout=2.0)
        except Exception as e:
            logger.warning(f"Error joining ping sender thread: {e}")

        try:
            if self._ws.is_alive():
                self._ws.join(timeout=2.0)
        except Exception as e:
            logger.warning(f"Error joining WebSocket manager thread: {e}")

        for thread in find_threads_by_name("send_ping"):
            try:
                _async_raise(thread.ident, SystemExit)
            except Exception as e:
                logger.warning(f"Error killing ping thread: {e}")

        self._callback = None
        logger.info("Unsubscribed from real-time data.")

    async def reset(self):
        old_callback = self._callback
        await self.unsubscribe_realtime_data()
        self._ws = self._create_ws_manager()
        self._info = Info(base_url=self.base_url)
        if old_callback:
            await self.subscribe_realtime_data(old_callback)
        logger.info("Hyperliquid data source reset.")

    async def get_next_bar(self) -> Optional[List[TickerData]]:
        # Not applicable for this real-time-only source.
        return None
