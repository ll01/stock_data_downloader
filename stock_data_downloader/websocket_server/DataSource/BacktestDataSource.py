import asyncio

from enum import Enum
from typing import Dict, Any, List, AsyncGenerator, Optional, Callable, cast, Awaitable
from stock_data_downloader.websocket_server.DataSource.BarResponse import BarResponse
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)
from stock_data_downloader.data_processing.simulation import (
    GBMSimulator,
    HestonSimulator,
    ISimulator,
)
from stock_data_downloader.models import (
    BackTestMode,
    BacktestDataSourceConfig,
    TickerConfig,
    TickerData,
)

import logging
logger = logging.getLogger(__name__)


    

class BacktestDataSource(DataSourceInterface):
    def __init__(
        self,
        ticker_configs: Optional[Dict[str, TickerConfig]] = None,
        backtest_config: Optional[BacktestDataSourceConfig] = None,
        global_config: Optional[Any] = None,
        ready_for_next_bar: Optional[asyncio.Event] = None,
    ):
        """
        Initialize BacktestDataSource.

        This constructor accepts both the new explicit signature and older
        kwargs-based construction with global_config for backward compatibility.

        Args:
            ticker_configs: Dict of ticker configurations.
            backtest_config: BacktestDataSourceConfig instance.
            global_config: Optional global_config parameter from older API versions.
            ready_for_next_bar: Event used to pace synchronous backtests.
        """
        # Handle legacy init pattern where a single config dict was provided
        if backtest_config is None and global_config is not None:
            backtest_config = global_config
        if ticker_configs is None and hasattr(backtest_config, "ticker_configs"):
            ticker_configs = getattr(backtest_config, "ticker_configs", {})

        # Support legacy dict configs
        if isinstance(backtest_config, dict):
            try:
                backtest_config = BacktestDataSourceConfig(**backtest_config)
            except Exception as e:
                logger.error(f"Failed to convert dict to BacktestDataSourceConfig: {e}", exc_info=True)
                raise

        # Ensure we have non-None defaults to avoid runtime errors
        self.backtest_config = backtest_config or BacktestDataSourceConfig(
            source_type="backtest",
            backtest_model_type="gbm",
            start_prices={},
            timesteps=0,
            interval=0.0,
            ticker_configs={}
        )
        # Ensure ticker_configs from config if not directly provided
        if not ticker_configs and hasattr(self.backtest_config, "ticker_configs"):
            self.ticker_configs = self.backtest_config.ticker_configs
        else:
            self.ticker_configs = ticker_configs or {}
        super().__init__(tickers=list(self.ticker_configs.keys()))
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
        # Number of precomputed time-steps that have been exposed as historical data
        # This is used to start per-client pointers after the historical window so
        # clients do not receive duplicate timestamps.
        self._historical_step_count: int = 0
        self.mode =  self.backtest_config.backtest_mode or BackTestMode.PULL

        # Log ticker count for debugging
        logger.info(f"Initialized backtest data source with {len(self.tickers)} tickers: {self.tickers}")
        logger.info(f"Backtest mode: {self.mode}")

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
        if self.mode == BackTestMode.PUSH:
            self._running = True
            asyncio.create_task(self.stream_price_updates())
        else:
            # pull mode: do not auto-stream; server drives via get_next_bar_for_client
            self._running = False
            # Precompute all bars immediately for synchronous mode
            self._ensure_precomputed()

    

        
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
        self, tickers: List[str] = [], interval: str = "", history_steps: Optional[int] = None
    ) -> List[TickerData]:
        """Return historical data for backtesting.

        If history_steps is provided, return only the most recent `history_steps`
        timesteps. If not provided, default to 20% of precomputed timesteps
        (minimum 1). This method sets `self._historical_step_count` to the
        number of timesteps actually returned so clients will begin after that offset.

        NOTE: This preserves the precomputed isolation semantics while avoiding
        sending the entire simulation as history by default.
        """
        # Ensure the precomputed sequence exists (builds simulator once)
        if self.simulator is None:
            self._initialize_simulator()
        assert self.simulator is not None, "Simulator must be initialized for historical data"

        # Build precomputed if not already present
        self._ensure_precomputed()

        total_steps = len(self._precomputed)
        if total_steps == 0:
            self._historical_step_count = 0
            return []

    
        if history_steps is None:
            history_steps = max(1, int(round(0.2 * total_steps)))

       
        history_steps = max(0, min(history_steps, total_steps))

       
        if history_steps == total_steps:
            selected_pre = self._precomputed
        elif history_steps == 0:
            selected_pre = []
        else:
            selected_pre = self._precomputed[:history_steps]

        self._historical_step_count = len(selected_pre)

        # Flatten selected_pre into combined_data
        combined_data: List[TickerData] = []
        for step_bars in selected_pre:
            combined_data.extend(step_bars)

        logger.debug(
            f"BacktestDataSource: prepared {len(combined_data)} historical ticks "
            f"spanning {self._historical_step_count} timesteps "
            f"(requested_history_steps={history_steps}, total_steps={total_steps})"
        )

        # If no tickers are specified, return all flattened data
        if not tickers:
            return combined_data

        # Filter data for the requested tickers
        return [bar for bar in combined_data if bar.ticker in tickers]

    async def unsubscribe_realtime_data(self):
        self._callback = None

    async def reset(self):
        """Reset the backtest data source to start a new simulation"""
        self.current_step = 0
        self.client_steps.clear()
        self.step_locks.clear()
        self._precomputed.clear()
        # Clear historical-step marker so new connections/historical requests will rebuild correctly
        self._historical_step_count = 0
        if self.simulator is not None:
            self.simulator.reset()
        old_callback = self._callback
        await self.unsubscribe_realtime_data()
        if old_callback:
            await self.subscribe_realtime_data(old_callback)

    async def reset_client(self, client_id: str):
        self.client_steps.pop(client_id, None)
        self.step_locks.pop(client_id, None)

    async def get_next_bar(self) -> BarResponse:
        if self.mode == BackTestMode.PUSH:
            # In push mode, we don't support get_next_bar directly
            return BarResponse(
                data=[],
                error_message="This data source does not support get_next_bar in push mode."
            )
        # Initialize simulator if not already done
        if self.simulator is None:
            self._initialize_simulator()
        assert self.simulator is not None, "Simulator must be initialized for next bar"

        # Check if we've reached the end of the simulation
        if self.current_step >= self.backtest_config.timesteps:
            return BarResponse(
                data=[],
                error_message="End of backtest simulation reached."
            )

        # Get the next bar and increment the step counter
        self.current_step += 1
        return BarResponse(
            data=self.simulator.next_bars(),
            error_message=None
        )

    def _ensure_precomputed(self):
        if self._precomputed:
            return
        # build once from simulator for isolation across clients
        if self.simulator is None:
            self._initialize_simulator()
        assert self.simulator is not None
        pre: list[list[TickerData]] = []
    
        self.simulator.reset()
        for _ in range(self.backtest_config.timesteps):
            bars = self.simulator.next_bars()
            pre.append(bars)
        self._precomputed = pre
 
        self.current_step = 0

    async def get_next_bar_for_client(self, client_id: str) -> BarResponse:
        """
        Get the next bar of data for a specific client in synchronous (pull) mode.

        Returns a BarResponse where `data` is a list of TickerData and
        `error_message` is a string describing the end-of-simulation or an error.
        """
        try:
            # Ensure precomputed bars exist
            self._ensure_precomputed()

            # Initialize client state if not exists
            if client_id not in self.step_locks:
                self.step_locks[client_id] = asyncio.Lock()
            if client_id not in self.client_steps:
                # Start the client's pointer after any historical timesteps already sent.
                start_step = getattr(self, "_historical_step_count", 0)
                self.client_steps[client_id] = start_step

            async with self.step_locks[client_id]:
                current_step = self.client_steps[client_id]

                # Check if simulation has ended
                if current_step >= len(self._precomputed):
                    return BarResponse(data=[], error_message="End of backtest simulation reached.")

                # Get the next bar
                bar_data = self._precomputed[current_step]
                self.client_steps[client_id] = current_step + 1

                return BarResponse(data=bar_data, error_message=None)
        except Exception as e:
            logger.exception(f"Error getting next bar for client {client_id}: {e}")
            return BarResponse(data=[], error_message=str(e))
    
    def _initialize_simulator(self):
        """Initialize the simulator based on model type"""
        # Set up current_prices from start_prices
        for ticker, price in self.backtest_config.start_prices.items():
            self.current_prices[ticker] = price
        
        # Use model type from config, default to GBM if not specified
        model_type = self.backtest_config.backtest_model_type or "gbm"
        
        if model_type == "heston":
            self.simulator = HestonSimulator(
                stats=self.ticker_configs,
                start_prices=self.current_prices,
                dt=self.backtest_config.interval,
                seed=self.backtest_config.seed,
            )
        elif model_type in ["gbm", "brownian"]:
            self.simulator = GBMSimulator(
                stats=self.ticker_configs,
                start_prices=self.backtest_config.start_prices,
                dt=self.backtest_config.interval,
                seed=self.backtest_config.seed,
            )
        else:
            raise ValueError(f"Unsupported backtest model type: {model_type}")
