from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Optional


@dataclass
class Order:
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: str
    cloid: Optional[str] = None
    args: Optional[Dict] = None

@dataclass
class OrderResult:
    cloid: Optional[str]
    oid:str
    status: str
    side: str
    price: float
    quantity: float
    symbol: str
    success: bool
    timestamp: str
    message: Optional[str] = None


# SIDEMAP = {
#     "BUY".casefold(): "BUY",
#     "SELL".casefold(): "SELL",
#     "SHORT".casefold(): "SELL",
#     "COVER".casefold(): "BUY"
# }

class ExchangeInterface(ABC):
    """Abstract base class for exchange integrations"""

    @abstractmethod
    async def place_order(self, orders: List[Order]) -> List[OrderResult]:
        """Place a market order on the exchange"""
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """Get account balances"""
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Check order status by ID"""
        pass

    @abstractmethod
    async def subscribe_to_orders(
        self, order_ids: List[str], callback: Callable[[str, Any], None]
    ):
        pass

    @abstractmethod
    async def unsubscribe_to_orders(self, order_ids: List[str]):
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID"""
        pass
