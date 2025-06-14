from abc import ABC, abstractmethod
from typing import Callable, Dict, Any, List, Optional
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult
from stock_data_downloader.websocket_server.portfolio import Portfolio


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
