import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import simulate_heston_prices

logger = logging.getLogger(__name__)

class HestonModelDataSource(DataSourceInterface):
    """
    A DataSource that generates stock data using the Heston model for stochastic volatility.
    """
    def __init__(self, stats: Dict[str, TickerStats], start_prices: Dict[str, float], timesteps: int = 252, interval: float = 1.0/252, seed: Optional[int] = None, wait_time: float = 1.0):
        self.stats = stats
        self.start_prices = start_prices
        self.timesteps = timesteps
        self.interval = interval # dt for simulation
        self.seed = seed
        self.wait_time = wait_time

        self._simulation_task: Optional[asyncio.Task] = None
        # self._callback: Optional[Callable[[str, Any], None]] = None
        self.simulated_prices: Dict[str, List[Dict[str, float]]] = self._generate_prices()

    def _generate_prices(self) -> Dict[str, List[Dict[str, float]]]:
        """Generate synthetic prices using the Heston model."""
        logger.debug(f"Generating {self.timesteps} timesteps of Heston model data...")
        return simulate_heston_prices(
            self.stats,
            self.start_prices,
            self.timesteps,
            self.interval,
            self.seed
        )

    async def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> Dict[str, List[Dict[str, float]]]:
        """Return pre-generated simulated prices."""
        logger.debug("Providing historical data from Heston simulation.")
        # Filter for requested tickers if provided
        if tickers:
            return {ticker: self.simulated_prices[ticker] for ticker in tickers if ticker in self.simulated_prices}
        return self.simulated_prices

    async def subscribe_realtime_data(self, callback:  Optional[Callable[[Any], None]] = None):
        """Starts an async task to deliver pre-generated data step by step."""
        if self._simulation_task and not self._simulation_task.done():
            await self.unsubscribe_realtime_data()
        
        self._callback = callback
        logger.debug(f"Starting real-time Heston simulation task with {self.wait_time}s interval...")
        self._simulation_task = asyncio.create_task(self._realtime_simulation_task())

    async def unsubscribe_realtime_data(self):
        """Cancels the simulation task."""
        if self._simulation_task and not self._simulation_task.done():
            self._simulation_task.cancel()
            try:
                await self._simulation_task
            except asyncio.CancelledError:
                logger.debug("Heston real-time simulation task cancelled.")
            finally:
                self._simulation_task = None
                self._callback = None

    async def _realtime_simulation_task(self):
        """Internal task to iterate through simulated data and notify the callback."""
        if not self._callback:
            return
        try:
            for i in range(self.timesteps):
                current_step_payload: List[Dict[str, Any]] = []
                for ticker, data_list in self.simulated_prices.items():
                    if i < len(data_list):
                        ohlc_data = data_list[i]
                        payload_item = {"ticker": ticker, **ohlc_data}
                        current_step_payload.append(payload_item)
                
                # Use the notifycallback from the interface
                await self._notify_callback("price_update", current_step_payload)
                await asyncio.sleep(self.wait_time)
            logger.debug("Heston real-time simulation finished.")
        except asyncio.CancelledError:
            logger.debug("Heston real-time simulation task received cancellation.")
            raise
        finally:
            self._simulation_task = None
            self._callback = None
            
    async def reset(self):
        """Regenerates synthetic prices."""
        logger.debug("Resetting HestonModelDataSource...")
        if self._simulation_task:
            await self.unsubscribe_realtime_data()
        
        self.seed = None if self.seed is None else self.seed + 1
        logger.debug(f"New seed for generation: {self.seed}")
        self.simulated_prices = self._generate_prices()
        logger.debug("HestonModelDataSource data regeneration complete.")