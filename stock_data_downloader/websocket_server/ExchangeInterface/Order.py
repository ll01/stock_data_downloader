from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Order:
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: str
    cloid: Optional[str] = None
    args: Optional[Dict] = None