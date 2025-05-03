import asyncio
from typing import Any, Callable, Dict, List, Optional
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.data_processing.TickerStats import TickerStats

from stock_data_downloader.data_processing.simulation import simulate_prices

class BrownianMotionDataSource(DataSourceInterface):
    def __init__(self, stats: Dict[str, TickerStats], start_prices: Dict[str, float], timesteps: int = 252, interval: float = 1.0, seed: Optional[int] = None, wait_time: float = 1.0):
        self.stats = stats
        self.start_prices = start_prices
        self.timesteps = timesteps
        self.interval = interval
        self.seed = seed
        self.wait_time = wait_time

       
        self._simulation_task: Optional[asyncio.Task] = None
        self._callback: Optional[Callable[[str, Any], None]] = None # Store the callback here

        self.simulated_prices: Dict[str, List[Dict[str, float]]] = self._generate_prices()


    def _generate_prices(self) -> Dict[str, List[Dict[str, float]]]:
        """Generate synthetic prices using GBM."""
        print(f"Generating {self.timesteps} timesteps of Brownian Motion data...")
        return simulate_prices(
            self.stats,
            self.start_prices,
            self.timesteps,
            self.interval, # Use the simulation interval
            self.seed
        )


    async def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> Dict[str, List[Dict[str, float]]]:
        """Return pre-generated simulated prices."""
        print("Providing historical data from simulation.")
        return self.simulated_prices

    async def subscribe_realtime_data(self, callback: Callable[[str, Any], None]):
        """
        Subscribe to real-time data simulation.
        Starts an async task to deliver pre-generated data step by step.
        """
        if self._simulation_task and not self._simulation_task.done():
            print("Existing real-time subscription found, unsubscribing first.")
            await self.unsubscribe_realtime_data()

        self._callback = callback 

      
        print(f"Starting real-time simulation task with {self.wait_time}s interval...")
        self._simulation_task = asyncio.create_task(self._realtime_simulation_task())


    async def unsubscribe_realtime_data(self):
        """
        Unsubscribe from real-time data simulation.
        Cancels the simulation task.
        """
        if self._simulation_task and not self._simulation_task.done():
            print("Cancelling real-time simulation task...")
            self._simulation_task.cancel()
            try:
                await self._simulation_task
            except asyncio.CancelledError:
                print("Real-time simulation task cancelled.")
            finally:
                self._simulation_task = None # Clear the task reference
                self._callback = None # Clear the callback
        else:
            print("No active real-time simulation task to unsubscribe from.")


    async def _realtime_simulation_task(self):
        """
        Internal task to iterate through simulated data and notify the callback.
        """
        if not self._callback:
            print("Warning: Real-time simulation task started without a callback.")
            return

        try:
            for i in range(self.timesteps):
                current_step_payload: List[Dict[str, Any]] = []
                for ticker, data_list in self.simulated_prices.items():
                    if i < len(data_list):
                        ohlc_data = data_list[i]
                        payload_item = {"ticker": ticker, **ohlc_data}
                        current_step_payload.append(payload_item)
                await self._notify_callback("price_update", current_step_payload)
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
        Regenerates synthetic prices and stops any active real-time simulation task.
        """
        print("Resetting BrownianMotionDataSource...")
        # 1. Stop any active real-time simulation task
        if self._simulation_task and not self._simulation_task.done():
            print("Resetting: Cancelling existing real-time simulation task...")
            self._simulation_task.cancel()
            try:
                # Wait for the task to be cancelled cleanly
                await self._simulation_task
            except asyncio.CancelledError:
                print("Resetting: Real-time simulation task cancelled successfully.")
            except Exception as e:
                 print(f"Resetting: Error waiting for task cancellation: {e}")
            finally:
                # Ensure state is clean after attempt, in case finally block in task didn't run
                self._simulation_task = None
                self._callback = None


        # 2. Update seed and regenerate simulated prices
        # Update seed (optional, as in your original code)
        self.seed = None if self.seed is None else self.seed + 1
        print(f"New seed for generation: {self.seed}")

        self.simulated_prices = self._generate_prices()
        print("BrownianMotionDataSource data regeneration complete.")