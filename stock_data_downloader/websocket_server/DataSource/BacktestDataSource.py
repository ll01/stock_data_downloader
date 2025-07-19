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
        self, ticker_configs: Dict[str, TickerConfig], backtest_config: BacktestDataSourceConfig
    ):
        super().__init__(tickers=list(ticker_configs.keys()))
        self.backtest_config = backtest_config
        self.ticker_configs = ticker_configs
        self.simulator: ISimulator
        self._callback = None
        self._running = False
        self._generator_task = None

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

    
        for ticker, price in self.backtest_config.start_prices.items():
            self.current_prices[ticker] = price

        logger.info(
            f"Starting backtest simulation with model type: {self.backtest_config.backtest_model_type}"
        )

        try:
            # Set up the appropriate generator based on model type
            if self.backtest_config.backtest_model_type == "heston":
                self.simulator = HestonSimulator(
                    stats=self.backtest_config.ticker_configs,
                    start_prices=self.current_prices,
                    dt=self.backtest_config.interval,
                    seed=self.backtest_config.seed,
                )
            elif self.backtest_config.backtest_model_type in ["gbm", "brownian"]:
                # Convert TickerConfig to TickerStats

                self.simulator = GBMSimulator(
                    stats=self.backtest_config.ticker_configs,  # Dict[str, TickerConfig]
                    start_prices=self.backtest_config.start_prices,
                    dt=self.backtest_config.interval,
                    seed=self.backtest_config.seed,
                )
            else:
                available_types = ["heston", "gbm"]
                logger.error(
                    "Unsupported backtest model type: "
                    f"{self.backtest_config.backtest_model_type}. ",
                    f"Available types: {', '.join(available_types)}"
                )
                raise ValueError(
                    "Unsupported backtest model type: ",
                    f"{self.backtest_config.backtest_model_type}"
                )

            # Process data from the generator
            max_time_steps = self.backtest_config.timesteps
            try:
                logger.info(f"Starting data generation for {len(self.tickers)} tickers")
                for _ in range(max_time_steps):
                    tick_batch =  self.simulator.next_bars()
                    await self._notify_callback("price_update", tick_batch)
                    

                # Signal the end of the simulation with a standardized message
                logger.info("Backtest simulation completed successfully")
                self.simulator.reset()
                await self._notify_callback("simulation_end", None)

            except Exception as e:
                logger.error(f"Error in backtest data generation: {e}", exc_info=True)
                # Ensure we still signal simulation end even on error
                await self._notify_callback("simulation_end", { "error": str(e)})
        except Exception as e:
            logger.error(f"Failed to initialize backtest generator: {e}", exc_info=True)
            raise

    async def get_historical_data(
        self, tickers: List[str] = [], interval: str = ""
    ) -> List[TickerData]:
        # BacktestDataSource does not provide historical data directly
        return []

    async def unsubscribe_realtime_data(self):
        self._callback = None

    async def reset(self):
        """Reset the backtest data source to start a new simulation"""
        old_callback = self._callback
        await self.unsubscribe_realtime_data()
        if old_callback:
            await self.subscribe_realtime_data(old_callback)
