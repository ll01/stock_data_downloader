from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class HestonConfig(BaseModel):
    kappa: float
    theta: float
    xi: float
    rho: float

class GBMConfig(BaseModel):
    mean: float
    sd: float

class TickerConfig(BaseModel):
    heston: Optional[HestonConfig] = None
    gbm: Optional[GBMConfig] = None

class TickerData(BaseModel):
    ticker: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float  # Changed from 'price' to 'close'
    volume: float