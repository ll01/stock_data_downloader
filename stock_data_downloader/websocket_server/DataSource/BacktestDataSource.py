from typing import Dict, Any, List, AsyncGenerator, Optional
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.data_processing.simulation import generate_heston_ticks, generate_gbm_ticks
from stock_data_downloader.models import TickerConfig
from stock_data_downloader.data_processing.TickerStats import TickerStats

def convert_to_ticker_stats(ticker_config: TickerConfig) -> TickerStats:
    """Convert TickerConfig to TickerStats based on the model type"""
    if ticker_config.gbm:
        return TickerStats(
            mean=ticker_config.gbm.mean,
            sd=ticker_config.gbm.sd
        )
    elif ticker_config.heston:
        # For Heston, we use mean=0 since it's not used in the model
        return TickerStats(mean=0, sd=0)
    else:
        raise ValueError("TickerConfig must have either gbm or heston config")

class BacktestDataSource(DataSourceInterface):
    def __init__(self, ticker_configs: Dict[str, TickerConfig], global_config: dict):
        super().__init__(tickers=list(ticker_configs.keys()))
        self.config = global_config
        self.ticker_configs = ticker_configs
        self.generator: Optional[AsyncGenerator] = None
        self._callback = None
        
    async def subscribe_realtime_data(self, callback):
        self._callback = callback
        model_type = self.config.get('model_type', 'heston')
        
        # Initialize current prices from config
        for ticker, price in self.config['start_prices'].items():
            self.current_prices[ticker] = price
            
        if model_type == 'heston':
            self.generator = generate_heston_ticks(
                stats={k: v.heston.model_dump() for k,v in self.ticker_configs.items() if v.heston},
                start_prices=self.config['start_prices'],
                timesteps=self.config['timesteps'],
                dt=self.config['interval'],
                seed=self.config.get('seed')
            )
        elif model_type == 'gbm':
            # Convert TickerConfig to TickerStats
            stats = {k: convert_to_ticker_stats(v) for k,v in self.ticker_configs.items()}
            self.generator = generate_gbm_ticks(
                stats=stats,
                start_prices=self.config['start_prices'],
                timesteps=self.config['timesteps'],
                interval=self.config['interval'],
                seed=self.config.get('seed')
            )
            
        if self.generator:
            async for tick_batch in self.generator:
                # Update current prices for each tick in batch
                for tick in tick_batch:
                    self.current_prices[tick['ticker']] = tick['close']
                    
                # Notify callback with the batch if available
                if callable(self._callback):
                    self._callback(tick_batch)

    async def get_historical_data(self, tickers: List[str] = [], interval: str = "") -> List[Dict[str, Any]]:
        # BacktestDataSource does not provide historical data directly
        return []

    async def unsubscribe_realtime_data(self):
        self.generator = None
        self._callback = None
