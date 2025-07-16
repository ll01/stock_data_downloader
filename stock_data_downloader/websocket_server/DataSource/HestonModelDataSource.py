import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, AsyncGenerator
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import generate_heston_ticks

logger = logging.getLogger(__name__)

class HestonModelDataSource(DataSourceInterface):
    """
    A DataSource that generates stock data using the Heston model for stochastic volatility.
    """
    def __init__(self, stats: Dict[str, TickerStats], start_prices: Dict[str, float], timesteps: int = 252, interval: float = 1.0/252, seed: Optional[int] = None, wait_time: float = 1.0):
        super().__init__(list(stats.keys()), str(interval))
        self.stats = stats
        self.start_prices = start_prices
        self.timesteps = timesteps
        self.interval = interval # dt for simulation
        self.seed = seed
        self.wait_time = wait_time

        self._simulation_task: Optional[asyncio.Task] = None

    def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Yields historical data from the Heston simulation, one timestep at a time."""
        logger.debug("Streaming historical data from Heston simulation...")
        return generate_heston_ticks(
            self.stats,
            self.start_prices,
            self.timesteps,
            self.interval,
            self.seed
        )

    async def subscribe_realtime_data(self, callback: Optional[Callable[[Any], None]] = None):
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
        """Internal task to iterate through the simulation generator and notify the callback."""
        if not self._callback:
            return
        try:
            data_generator = generate_heston_ticks(
                self.stats, self.start_prices, self.timesteps, self.interval, self.seed
            )
            async for timestep_data in data_generator:
                await self._notify_callback("price_update", timestep_data)
                await asyncio.sleep(self.wait_time)

            logger.debug("Heston real-time simulation finished.")
        except asyncio.CancelledError:
            logger.debug("Heston real-time simulation task received cancellation.")
            raise
        finally:
            self._simulation_task = None
            self._callback = None
            
    async def reset(self):
        """Resets the simulation by stopping any active task and updating the seed."""
        logger.debug("Resetting HestonModelDataSource...")
        if self._simulation_task:
            await self.unsubscribe_realtime_data()
        
        self.seed = None if self.seed is None else self.seed + 1
        logger.debug(f"New seed for generation: {self.seed}")
        logger.debug("HestonModelDataSource data regeneration complete.")
