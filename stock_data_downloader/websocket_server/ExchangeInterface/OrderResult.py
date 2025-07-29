from dataclasses import dataclass
from typing import Optional

@dataclass
class OrderResult:
    cloid: Optional[str]
    oid: str
    status: str
    side: str
    price: float
    quantity: float
    symbol: str
    success: bool
    timestamp: str
    message: Optional[str] = None