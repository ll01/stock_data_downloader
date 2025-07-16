from abc import ABC, abstractmethod
from collections.abc import Callable
import logging
from typing import Any, Dict, List, Optional, Set, AsyncGenerator

# from websockets.asyncio.client import ServerConnection

class DataSourceInterface(ABC):
    """Abstract base class for market data sources."""

    def __init__(self, tickers: List[str] = [],  interval: Optional[str] = None):
        self._subscribed_tickers: Set[str] = set(tickers) if tickers else set()
        self._callback: Optional[Callable[[Any], None]] = None
        self.current_prices: Dict[str, float] = {} # Store latest prices
        self.tickers = tickers

    @abstractmethod
    async def get_historical_data(self, tickers: List[str] = [] , interval: str= "") -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Fetch historical data (e.g., OHLCV) for backtesting."""
        pass

    @abstractmethod
    async def subscribe_realtime_data(self, callback: Callable):
        """Subscribe to real-time data (e.g., via WebSocket) and trigger `callback` on updates."""
        pass

    @abstractmethod
    async def unsubscribe_realtime_data(self):
        """Unsubscribe from real-time data streams."""
        pass

    async def _notify_callback(self, msg_type: str, payload: Any):
        """Helper to safely call the callback."""
        if self._callback:
            try:
                # Update internal current_prices before notifying
                if msg_type == "price_update" and isinstance(payload, list):
                    for update in payload:
                        if isinstance(update, dict) and "ticker" in update and "close" in update:
                             # Use 'close' price as the representative current price
                            self.current_prices[update["ticker"]] = float(update["close"])
                self._callback(payload)
            except Exception:
                logging.exception("Error occurred in data source callback")
        else:
            logging.warning("Data source callback not set, cannot notify.")
    
    