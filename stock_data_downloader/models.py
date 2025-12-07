from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union, Literal
from dataclasses import dataclass

class HestonConfig(BaseModel):
    kappa: float
    theta: float
    xi: float
    rho: float

class GHARCHConfig(BaseModel):
    omega: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    initial_variance: Optional[float] = None

class GBMConfig(BaseModel):
    mean: float
    sd: float

class TickerConfig(BaseModel):
    heston: Optional[HestonConfig] = None
    gbm: Optional[GBMConfig] = None
    gharch: Optional[GHARCHConfig] = None
    start_price: Optional[float] = None
    
class TickerData(BaseModel):
    ticker: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float  # Changed from 'price' to 'close'
    volume: float

class CCXTDataSourceConfig(BaseModel):
    exchange_id: str
    credentials: Dict[str, str]
    tickers: List[str]
    interval: str = "1m"
    sandbox: bool = False
    options: Optional[Dict[str, Any]] = None
    api_config: Dict[str, Any] = {}
    
class BackTestMode(str, Enum):
    PUSH = "push"
    PULL = "pull"
    
class BacktestDataSourceConfig(BaseModel):
    source_type: str = "backtest"
    backtest_model_type: str = "gbm"
    start_prices: Dict[str, float]
    timesteps: int
    interval: float
    seed: Optional[int] = None
    ticker_configs: Dict[str, TickerConfig]
    # Optional override: how many historical timesteps to return when a client
    # requests historical data. When unset, the data source default is used
    # (BacktestDataSource.get_historical_data defaults to 20% of timesteps).
    history_steps: Optional[int] = None
    # Default to PUSH so subscribe_realtime_data emits data by default.
    # Tests that require pull-mode should explicitly set backtest_mode to BackTestMode.PULL.
    backtest_mode: Optional[BackTestMode] = BackTestMode.PUSH
    # Map of ticker -> timestep when it delists (stops sending data)
    delisted_assets: Dict[str, int] = {}
    # Monte Carlo simulation options
    randomize_universe: bool = False
    randomize_universe_size: Optional[int] = None
    include_delisted_probability: float = 0.0


    
class HyperliquidDataSourceConfig(BaseModel):
    """Configuration for Hyperliquid data source"""
    source_type: Literal["hyperliquid"]
    network: str = "mainnet"  # "mainnet" or "testnet"
    tickers: List[str]
    interval: str = "1m"
    api_config: Dict[str, Any] = {}

class DataSourceConfig(BaseModel):
    """Unified configuration for all data sources"""
    source_type: str
    config: Union[BacktestDataSourceConfig, HyperliquidDataSourceConfig]

class UriConfig(BaseModel):
    """Configuration for URI-based data sources"""
    host: str = "0.0.0.0"
    port: int = 8000
    
class ServerConfig(BaseModel):
    """Configuration for WebSocket server"""
    data_downloader: UriConfig = UriConfig(host="localhost", port=8000)
    broker: UriConfig = UriConfig(host="localhost", port=8001)
    ping_interval: Optional[int] = 20
    ping_timeout: Optional[int] = 20

class TestExchangeConfig(BaseModel):
    type: Literal["test"]
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 5.0
    slippage_bps: float = 0.0
    slippage_model: Literal["fixed", "normal"] = "fixed"
    slippage_variability_bps: float = 0.0

class HyperliquidExchangeConfig(BaseModel):
    type: Literal["hyperliquid"]
    network: Literal["mainnet", "testnet"] = "mainnet"
    api_config: dict[str, str]  # secret_key, wallet_address

class CCXTExchangeConfig(BaseModel):
    type: Literal["ccxt"]
    exchange_id: str
    sandbox: bool = False
    credentials: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    api_config: dict[str, str] 

class ExchangeConfig(BaseModel):
    exchange: TestExchangeConfig | HyperliquidExchangeConfig | CCXTExchangeConfig
    
class AppConfig(BaseModel):
    """Complete application configuration"""
    data_source: DataSourceConfig
    server: ServerConfig
    initial_cash: float = 100000.0
    exchange: ExchangeConfig
