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

    @abstractmethod
    async def get_next_bar(self) -> Optional[List[TickerData]]:
        """
        Fetch the next single bar of data for all tickers.

        Returns:
            Optional[List[TickerData]]: The next bar of data, or None if no more data is available.
        """
        pass
    
    async def _notify_callback(self, kind_or_payload: Any, payload: Optional[Any] = None):
        """
        Notify the subscribed callback.

        Supports both calling conventions used in tests and older code:
          - _notify_callback(kind, payload)
          - _notify_callback(payload)  (kind is inferred as "price_update" or taken from payload["type"])

        This method will:
          - Normalize TickerData models to plain dicts before invoking the callback.
          - Update self.current_prices using the normalized payload.
          - Attempt to call the callback with (kind, payload) and fall back to (payload,) if necessary.
          - Support both async and sync callbacks.
        """
        if payload is None:
            # Single-argument form: treat argument as the payload
            payload = kind_or_payload
            if isinstance(payload, dict) and payload.get("type"):
                kind = payload.get("type")
            else:
                kind = "price_update"
        else:
            kind = kind_or_payload

        # Normalize payloads for price updates to a list of dicts and update current_prices
        try:
            if kind == "price_update" and payload is not None:
                normalized = []
                for tick in payload:
                    # Convert Pydantic model instances to dicts if necessary
                    if hasattr(tick, "model_dump"):
                        d = tick.model_dump()
                    elif isinstance(tick, dict):
                        d = tick
                    else:
                        # Best-effort conversion from objects with attributes
                        try:
                            d = {
                                "ticker": getattr(tick, "ticker", None),
                                "close": getattr(tick, "close", None),
                                "timestamp": getattr(tick, "timestamp", None),
                            }
                        except Exception:
                            d = tick
                    # Update current_prices if we have ticker & close
                    try:
                        if isinstance(d, dict) and d.get("ticker") is not None and d.get("close") is not None:
                            self.current_prices[d["ticker"]] = d["close"]
                    except Exception:
                        pass
                    normalized.append(d)
                payload = normalized
            else:
                # For other message types, if payload contains price-like dicts, update current_prices
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict) and "ticker" in item and "close" in item:
                            try:
                                self.current_prices[item["ticker"]] = item["close"]
                            except Exception:
                                pass
        except Exception:
            logging.exception("Error while normalizing payload for callback")

        # Invoke callback with flexible signature handling
        if self._callback:
            try:
                try:
                    res = self._callback(kind, payload)
                except TypeError:
                    # Callback may accept a single argument (payload)
                    res = self._callback(payload)

                # Await if the callback returned a coroutine / awaitable
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    await res
            except Exception:
                logging.exception("Error in data source callback")
        else:
            logging.warning("Data source callback not set, cannot notify.")