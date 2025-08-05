import asyncio
from typing import Dict, Any, List, AsyncGenerator, Optional, Callable, cast, Awaitable
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)
from stock_data_downloader.data_processing.simulation import (
    GBMSimulator,
    HestonSimulator,
    ISimulator,
)
from stock_data_downloader.models import (
    BacktestDataSourceConfig,
    TickerConfig,
    TickerData,
)

import logging
logger = logging.getLogger(__name__)


class BacktestDataSource(DataSourceInterface):
    def __init__(
        self, ticker_configs: Dict[str, TickerConfig], backtest_config: BacktestDataSourceConfig,
        ready_for_next_bar: Optional[asyncio.Event] = None
    ):
        super().__init__(tickers=list(ticker_configs.keys()))
        self.backtest_config = backtest_config
        self.ticker_configs = ticker_configs
        self.ready_for_next_bar = ready_for_next_bar
        self.simulator: Optional[ISimulator] = None
        self._callback = None
        self._running = False
        self._generator_task = None
        self.current_step = 0
        # precomputed bars for isolation
        self._precomputed: list[list[TickerData]] = []
        # per-client step tracking
        self.client_steps: Dict[str, int] = {}
        self.step_locks: Dict[str, asyncio.Lock] = {}
        # default to pull mode for backtests
        self.pull_mode: bool = True

        # Log ticker count for debugging
        logger.info(f"Initialized backtest data source with {len(self.tickers)} tickers: {self.tickers}")

    def enable_pull_mode(self, on: bool = True):
        self.pull_mode = on

    async def subscribe_realtime_data(self, callback: Callable[[str, Any], Awaitable[None]]):
        """
        Subscribe to simulated real-time data from the backtest generator.

        This method sets up the data generation based on the configured model type
        and streams the data to the provided callback function. It uses the standardized
        callback mechanism to ensure consistent behavior with other data sources.

        The callback will receive data in one of two formats:
        1. A list of dictionaries for price updates, where each dictionary contains:
           - ticker: The ticker symbol
           - close: The closing price
           - timestamp: ISO format timestamp
           - Additional OHLCV fields as available

        2. A dictionary with "type": "simulation_end" when the simulation completes,
           optionally with an "error" field if the simulation ended due to an error.

        Args:
            callback: Async function to call when new data is available.
                     The callback will receive data in a standardized format.
        """
    
        self._callback = callback
        if not self.pull_mode:
            self._running = True
            asyncio.create_task(self.stream_price_updates())
        else:
            # pull mode: do not auto-stream; server drives via get_next_bar_for_client
            self._running = False

    

        
    async def stream_price_updates(self):
        """Generate and send price updates, pausing between bars in backtest mode"""
        try:
            # Initialize simulator if needed
            if self.simulator is None:
                self._initialize_simulator()
            assert self.simulator is not None, "Simulator must be initialized before streaming"
            
            max_time_steps = self.backtest_config.timesteps
            logger.info(f"Starting backtest simulation for {max_time_steps} timesteps")
            
            for step in range(max_time_steps):
                if not self._running:
                    break
                
                # Get the next bar and increment the step counter
                self.current_step = step + 1
                tick_batch = self.simulator.next_bars()
                
                # Push data to callback
                if self._callback:
                    await self._notify_callback("price_update", tick_batch)
                
                # CRITICAL: Wait for TradingLoop to signal it's ready for next bar
                # Only do this if we're in backtest mode (have the event)
                if self.ready_for_next_bar:
                    logger.debug(f"BacktestDataSource pausing at step {self.current_step} - waiting for ready signal")
                    self.ready_for_next_bar.clear()
                    await self.ready_for_next_bar.wait()
                    logger.debug(f"BacktestDataSource resuming at step {self.current_step}")
            
            # Signal the end of the simulation
            if self._callback:
                logger.info("Backtest simulation completed successfully")
                await self._notify_callback("simulation_end", None)
        except asyncio.CancelledError:
            logger.info("Backtest data generation task cancelled")
        except Exception as e:
            logger.error(f"Error in backtest data generation: {e}", exc_info=True)
            if self._callback:
                await self._notify_callback("simulation_end", {"error": str(e)})
        finally:
            self._running = False
        # for ticker, price in self.backtest_config.start_prices.items():
        #     self.current_prices[ticker] = price
            
        # logger.info(
        #     f"Starting backtest simulation with model type: {self.backtest_config.backtest_model_type}"
        # )

        # try:
        #     # Set up the appropriate generator based on model type
        #     if self.backtest_config.backtest_model_type == "heston":
        #         self.simulator = HestonSimulator(
        #             stats=self.ticker_configs,
        #             start_prices=self.current_prices,
        #             dt=self.backtest_config.interval,
        #             seed=self.backtest_config.seed,
        #         )
        #     elif self.backtest_config.backtest_model_type in ["gbm", "brownian"]:
        #         # Convert TickerConfig to TickerStats

        #         self.simulator = GBMSimulator(
        #             stats=self.ticker_configs,  # Dict[str, TickerConfig]
        #             start_prices=self.backtest_config.start_prices,
        #             dt=self.backtest_config.interval,
        #             seed=self.backtest_config.seed,
        #         )
        #     else:
        #         available_types = ["heston", "gbm"]
        #         logger.error(
        #             "Unsupported backtest model type: "
        #             f"{self.backtest_config.backtest_model_type}. ",
        #             f"Available types: {', '.join(available_types)}"
        #         )
        #         raise ValueError(
        #             "Unsupported backtest model type: ",
        #             f"{self.backtest_config.backtest_model_type}"
        #         )

        #     # Process data from the generator
        #     max_time_steps = self.backtest_config.timesteps
        #     try:
        #         logger.info(f"Starting data generation for {len(self.tickers)} tickers")
        #         for _ in range(max_time_steps):
        #             tick_batch =  self.simulator.next_bars()
        #             await self._notify_callback("price_update", tick_batch)
        #             await asyncio.sleep(0)
                    

        #         # Signal the end of the simulation with a standardized message
        #         logger.info("Backtest simulation completed successfully")
        #         self.simulator.reset()
        #         await self._notify_callback("simulation_end", None)

        #     except Exception as e:
        #         logger.error(f"Error in backtest data generation: {e}", exc_info=True)
        #         # Ensure we still signal simulation end even on error
        #         await self._notify_callback("simulation_end", { "error": str(e)})
        # except Exception as e:
        #     logger.error(f"Failed to initialize backtest generator: {e}", exc_info=True)
        #     raise
        
    async def get_historical_data(
        self, tickers: List[str] = [], interval: str = ""
    ) -> List[TickerData]:
        # BacktestDataSource does not provide historical data directly
        # Generate realistic historical data (10 bars)
        historical_data = []
        # # Ensure simulator is initialized
        # if self.simulator is None:
        #     self._initialize_simulator()
        # assert self.simulator is not None, "Simulator must be initialized for historical data"
        # for _ in range(10):
        #     historical_data.extend(self.simulator.next_bars())
        return historical_data

    async def unsubscribe_realtime_data(self):
        self._callback = None

    async def reset(self):
        """Reset the backtest data source to start a new simulation"""
        self.current_step = 0
        self.client_steps.clear()
        self.step_locks.clear()
        self._precomputed.clear()
        if self.simulator is not None:
            self.simulator.reset()
        old_callback = self._callback
        await self.unsubscribe_realtime_data()
        if old_callback:
            await self.subscribe_realtime_data(old_callback)

    async def reset_client(self, client_id: str):
        self.client_steps.pop(client_id, None)
        self.step_locks.pop(client_id, None)

    async def get_next_bar(self) -> Optional[List[TickerData]]:
        # Initialize simulator if not already done
        if self.simulator is None:
            self._initialize_simulator()
        assert self.simulator is not None, "Simulator must be initialized for next bar"

        # Check if we've reached the end of the simulation
        if self.current_step >= self.backtest_config.timesteps:
            return None

        # Get the next bar and increment the step counter
        self.current_step += 1
        return self.simulator.next_bars()

    def _ensure_precomputed(self):
        if self._precomputed:
            return
        # build once from simulator for isolation across clients
        if self.simulator is None:
            self._initialize_simulator()
        assert self.simulator is not None
        pre: list[list[TickerData]] = []
        # use a fresh simulator copy to avoid mutating shared state further
        # Since simulator may have internal state, rebuild it for precompute
        self.simulator.reset()
        for _ in range(self.backtest_config.timesteps):
            bars = self.simulator.next_bars()
            # store as-is (TickerData are Pydantic models; they’re immutable enough for read)
            pre.append(bars)
        self._precomputed = pre
        # reset shared current_step for non-client get_next_bar
        self.current_step = 0

    async def get_next_bar_for_client(self, client_id: str) -> Optional[List[TickerData]]:
        # Ensure precomputed bars exist
        self._ensure_precomputed()
        # init lock and step
        if client_id not in self.step_locks:
            self.step_locks[client_id] = asyncio.Lock()
        if client_id not in self.client_steps:
            self.client_steps[client_id] = 0
        async with self.step_locks[client_id]:
            idx = self.client_steps[client_id]
            if idx >= len(self._precomputed):
                return None
            self.client_steps[client_id] = idx + 1
            return self._precomputed[idx]
    
    def _initialize_simulator(self):
        """Initialize the simulator based on model type"""
        # Set up current_prices from start_prices
        for ticker, price in self.backtest_config.start_prices.items():
            self.current_prices[ticker] = price
        
        if self.backtest_config.backtest_model_type == "heston":
            self.simulator = HestonSimulator(
                stats=self.ticker_configs,
                start_prices=self.current_prices,
                dt=self.backtest_config.interval,
                seed=self.backtest_config.seed,
            )
        elif self.backtest_config.backtest_model_type in ["gbm", "brownian"]:
            self.simulator = GBMSimulator(
                stats=self.ticker_configs,
                start_prices=self.backtest_config.start_prices,
                dt=self.backtest_config.interval,
                seed=self.backtest_config.seed,
            )
        else:
            raise ValueError(f"Unsupported backtest model type: {self.backtest_config.backtest_model_type}")
