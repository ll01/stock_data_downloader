import asyncio
from typing import Any, Callable, Dict, List, Optional, AsyncGenerator
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import generate_gbm_ticks

class BrownianMotionDataSource(DataSourceInterface):
    def __init__(self, stats: Dict[str, TickerStats], start_prices: Dict[str, float], timesteps: int = 252, interval: float = 1.0, seed: Optional[int] = None, wait_time: float = 1.0):
        super().__init__(list(stats.keys()), str(interval))
        self.stats = stats
        self.start_prices = start_prices
        self.timesteps = timesteps
        self.interval = interval
        self.seed = seed
        self.wait_time = wait_time

        self._simulation_task: Optional[asyncio.Task] = None

    async def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Yields historical data from the GBM simulation, one timestep at a time."""
        print("Streaming historical data from GBM simulation...")
        # The generator yields lists of dicts, which matches the required output structure.
        return generate_gbm_ticks(
            self.stats,
            self.start_prices,
            self.timesteps,
            self.interval,
            self.seed
        )

    async def subscribe_realtime_data(self, callback: Callable[[Any], None]):
        """
        Subscribe to real-time data simulation.
        Starts an async task to deliver generated data step by step.
        """
        if self._simulation_task and not self._simulation_task.done():
            print("Existing real-time subscription found, unsubscribing first.")
            await self.unsubscribe_realtime_data()

        self._callback = callback
        print(f"Starting real-time GBM simulation task with {self.wait_time}s interval...")
        self._simulation_task = asyncio.create_task(self._realtime_simulation_task())

    async def unsubscribe_realtime_data(self):
        """
        Unsubscribe from real-time data simulation by cancelling the task.
        """
        if self._simulation_task and not self._simulation_task.done():
            print("Cancelling real-time simulation task...")
            self._simulation_task.cancel()
            try:
                await self._simulation_task
            except asyncio.CancelledError:
                print("Real-time simulation task cancelled.")
            finally:
                self._simulation_task = None
                self._callback = None
        else:
            print("No active real-time simulation task to unsubscribe from.")

    async def _realtime_simulation_task(self):
        """
        Internal task to iterate through the simulation generator and notify the callback.
        """
        if not self._callback:
            print("Warning: Real-time simulation task started without a callback.")
            return

        try:
            data_generator = generate_gbm_ticks(
                self.stats, self.start_prices, self.timesteps, self.interval, self.seed
            )
            for timestep_data in data_generator:
                await self._notify_callback("price_update", timestep_data)
                await asyncio.sleep(self.wait_time)

            print("Real-time simulation finished (all timesteps delivered).")

        except asyncio.CancelledError:
            print("Real-time simulation task received cancellation signal.")
            raise
        except Exception as e:
            print(f"An error occurred in the real-time simulation task: {e}")
        finally:
            self._simulation_task = None
            self._callback = None
            print("Real-time simulation task finished.")

    async def reset(self):
        """
        Resets the simulation by stopping any active task and updating the seed.
        The generator will be recreated on the next call to subscribe or get_historical_data.
        """
        print("Resetting BrownianMotionDataSource...")
        if self._simulation_task and not self._simulation_task.done():
            await self.unsubscribe_realtime_data()
        
        # Increment the seed for the next simulation run
        self.seed = None if self.seed is None else self.seed + 1
        print(f"New seed for next simulation: {self.seed}")
        print("BrownianMotionDataSource reset complete.")
