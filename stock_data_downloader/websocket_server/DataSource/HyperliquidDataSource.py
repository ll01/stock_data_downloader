import asyncio
from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Dict, List, Optional, Tuple
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.utils.types import CandleSubscription
import logging
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)
from collections.abc import Callable
from hyperliquid.websocket_manager import WebsocketManager

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
        self.base_url = (
            constants.TESTNET_API_URL
            if network == "testnet"
            else constants.MAINNET_API_URL
        )
        self._info = Info(base_url=self.base_url)
        self._callback: Optional[Callable[[Any], None]] = None
        self.current_prices: Dict[str, float] = {}
        self.interval = interval
        self._subscriptions: List[Tuple[CandleSubscription, int]] = []
        self._ws = WebsocketManager(self.base_url)
        self._ws.daemon = True
        self._ws.ping_sender.daemon = True

    async def get_historical_data(
        self, tickers: List[str] = [], interval: str = ""
    ) -> List[Dict[str, Any]]:
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

    async def subscribe_realtime_data(self, callback: Callable[[Any], None]):
        """Subscribe to real-time price updates via WebSocket."""

        self._callback = callback
        self._ws.start()
        for thread in [self._ws.ping_sender]:
            if thread and isinstance(thread, threading.Thread) and thread.is_alive():
                thread.daemon = True
        for ticker in self.tickers:
            subscription: CandleSubscription = {
                "type": "candle",
                "coin": ticker,
                "interval": self.interval,
            }
            sub_id = self._ws.subscribe(subscription, callback=self._handle_ws_message)
            self._subscriptions.append(
                (
                    subscription,
                    sub_id,
                )
            )

    async def unsubscribe_realtime_data(self):
        """Unsubscribe from real-time data."""
        # 1) unsubscribe all WS subscriptions
        for sub, sub_id in self._subscriptions:
            self._info.unsubscribe(sub, sub_id)
        self._subscriptions.clear()
        self._callback = None

        # 2) stop the ping loop and the WebSocketApp
        self._ws.stop()
        self._ws.ws.close()
        self._ws.ws.keep_running = False

        # 3) wait for ping_sender to fully exit
        if self._ws.ping_sender.is_alive():
            self._ws.ping_sender.join()

        # 4) wait for the WebsocketManager thread to finish
        if self._ws.is_alive():
            self._ws.join()

        # 5) clean up
        del self._ws
        ws_tt = [t for t in threading.enumerate() if  isinstance(t, WebsocketManager)]
       

        for t in ws_tt:
            _async_raise(t.ident, SystemExit)

        ping_threads = find_threads_by_name("send_ping")

        for t in ping_threads:
            _async_raise(t.ident, SystemExit)

    def _map_candle_message(self, msg: dict) -> dict:
        """
        Map a raw WS candle message with short keys to a full-label dict.

        Input example:
        {
            't': 1746192900000,
            'T': 1746192959999,
            's': 'BTC',
            'i': '1m',
            'o': '96899.0',
            'h': '96899.0',
            'l': '96899.0',|
            'c': '96899.0',
            'v': '0.01',
            'n': 1
        }

        Output:
        {
            'start_timestamp': 1746192900000,
            'end_timestamp':   1746192959999,
            'ticker':          'BTC',
            'interval':        '1m',
            'open':            96899.0,
            'high':            96899.0,
            'low':             96899.0,
            'close':           96899.0,
            'volume':          0.01,
            'trade_count':     1
        }
        """
        return {
            # "start_timestamp": msg["t"],
            "timestamp": datetime.fromtimestamp(msg["T"]/1000, timezone.utc).isoformat(),
            "ticker": msg["s"],
            # "interval":        msg["i"],
            "open": float(msg["o"]),
            "high": float(msg["h"]),
            "low": float(msg["l"]),
            "close": float(msg["c"]),
            "volume": float(msg["v"]),
            # "trade_count":     int(msg["n"]),
        }

    def _handle_ws_message(self, message: Dict[str, Any]):
        """Process incoming WebSocket messages and forward to user callback."""
        try:
            candle_data = message.get("data")
            if not candle_data or message.get("channel") != "candle":
                return
            payload = self._map_candle_message(candle_data)

            if self._callback:
                self._callback(payload)
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    async def reset(self):
        """Reset data source."""
        await self.unsubscribe_realtime_data()
        if self._callback:
            await self.subscribe_realtime_data(self._callback)
        self._info = Info(base_url=self.base_url)
        logger.info("Hyperliquid data source reset complete.")

