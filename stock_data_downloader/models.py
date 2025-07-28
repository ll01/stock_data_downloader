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
    
class BacktestDataSourceConfig(BaseModel):
    source_type: str = "backtest"
    backtest_model_type: str = "gbm"
    start_prices: Dict[str, float]
    timesteps: int
    interval: float
    seed: Optional[int] = None
    ticker_configs: Dict[str, TickerConfig]
    backtest_mode: Optional[str] = None

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