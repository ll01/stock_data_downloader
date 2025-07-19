from abc import ABC, abstractmethod
from collections.abc import Callable
import logging
import asyncio
from typing import Any, Dict, List, Optional, Set, AsyncGenerator, Awaitable

from stock_data_downloader.models import TickerData

class DataSourceInterface(ABC):
    """
    Abstract base class for market data sources.
    
    This interface defines the common contract that all data sources must implement,
    ensuring a unified approach to streaming market data regardless of source type
    (backtest simulation or live market feed).
    """

    def __init__(self, tickers: List[str] = [], interval: Optional[str] = None):
        self._subscribed_tickers: Set[str] = set(tickers) if tickers else set()
        self._callback: Optional[Callable[[str, Any], Awaitable[None]]] = None
        self.current_prices: Dict[str, float] = {}  # Store latest prices
        self.tickers = tickers

    @abstractmethod
    async def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> List[TickerData]:
        """
        Fetch historical data (e.g., OHLCV).
        
        Args:
            tickers: List of ticker symbols to fetch data for. If empty, uses the instance's tickers.
            interval: Time interval for the data (e.g., "1m", "1h", "1d").
            
        Returns:
            List of dictionaries containing historical market data.
        """
        pass

    @abstractmethod
    async def subscribe_realtime_data(self, callback: Callable[[str, Any], Awaitable[None]]):
        """
        Subscribe to real-time data and trigger `callback` on updates.
        
        This method should establish the necessary connections to receive real-time
        market data and invoke the callback function whenever new data is available.
        
        The callback function should accept a single parameter containing the market data.
        For backtest sources that complete their simulation, a special message with
        {"type": "simulation_end"} should be sent through the callback.
        
        Args:
            callback: Async function to call when new data is available.
        """
        pass

    @abstractmethod
    async def unsubscribe_realtime_data(self):
        """
        Unsubscribe from real-time data streams.
        
        This method should clean up any connections or resources used for streaming data.
        """
        pass
    
    @abstractmethod
    async def reset(self):
        """
        Reset the data source state.
        
        For backtest sources, this should restart the simulation.
        For live sources, this might reconnect to the data feed.
        """
        pass
    
    async def _notify_callback(self, kind: str, payload: Any):
        if self._callback:
            try:
                if kind == "price_update":
                    # keep current_prices up-to-date
                    for tick in payload:
                        self.current_prices[tick.ticker] = tick.close
                await self._callback(kind, payload)
            except Exception:
                logging.exception("Error in data source callback")
        else:
            logging.warning("Data source callback not set, cannot notify.")