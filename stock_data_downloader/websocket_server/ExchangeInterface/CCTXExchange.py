import logging
from typing import List, Dict, Any, Callable, Optional
from datetime import datetime, timezone

import ccxt.async_support as ccxt

from stock_data_downloader.models import CCXTExchangeConfig
from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface,
)
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import (
    OrderResult,
)


class CCTXExchange(ExchangeInterface):
    """
    Implementation of ExchangeInterface using CCXT async support.
    Supports market orders, balance checks, and order status/cancellation.
    """

    def __init__(self, config: CCXTExchangeConfig):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cfg = config

        exchange_class = getattr(ccxt, config.exchange_id, None)
        if not exchange_class:
            raise ValueError(f"Exchange {config.exchange_id} not supported by CCXT")

        params = {
            "apiKey": config.credentials.get("api_key", ""),
            "secret": config.credentials.get("secret", ""),
            "password": config.credentials.get("password"),
            "enableRateLimit": True,
            "sandbox": config.sandbox,
            "options": config.options,
        }
        self.exchange = exchange_class(params)

    async def place_order(self, orders: List[Order]) -> List[OrderResult]:
        """
        Place one or more market orders on the exchange using a robust
        "place, then fetch" strategy to ensure accurate results across exchanges.

        Args:
            orders: List of Order objects to execute

        Returns:
            List of OrderResult objects with the outcome of each order placement.
        """
        results = []
        for order in orders:
            try:
                # Step 1: Place the order with create_order
                initial_response = await self.exchange.create_order(
                    symbol=order.symbol,
                    type="market",
                    side=order.side.lower(),
                    amount=order.quantity,
                    price=order.price,  # Often ignored for market orders but passed for completeness
                    params={"clientOrderId": order.cloid} if order.cloid else {},
                )
                order_id = initial_response["id"]

                # Step 2: Fetch the order details for accurate information
                # This is crucial for getting reliable filled price and quantity [cite: 66, 157]
                full_order_details = await self.exchange.fetch_order(
                    order_id, order.symbol
                )

                # Step 3: Map the reliable fetch_order response to OrderResult
                result = self._map_ccxt_to_order_result(full_order_details, order)
                results.append(result)

            except Exception as e:
                self.logger.error(f"Error placing order {order}: {e}")
                # Create a failure OrderResult
                results.append(
                    OrderResult(
                        success=False,
                        symbol=order.symbol,
                        side=order.side,
                        cloid=order.cloid,
                        message=str(e),
                    )
                )

        return results

    def _map_ccxt_to_order_result(
        self, ccxt_order: Dict[str, Any], original_order: Order
    ) -> OrderResult:
        """
        Maps a CCXT order structure (ideally from fetch_order) to the OrderResult dataclass.
        """
        status = ccxt_order.get("status")

        # Determine success based on the final status [cite: 140]
        is_success = status in ["closed", "filled"]

        # For market orders, 'average' is the reliable execution price, not 'price' [cite: 116, 117]
        exec_price = ccxt_order.get("average")
        if not exec_price and ccxt_order.get("cost") and ccxt_order.get("filled"):
            # Fallback calculation if 'average' is not provided [cite: 118]
            exec_price = ccxt_order["cost"] / ccxt_order["filled"]

        # 'filled' represents the executed quantity [cite: 124]
        filled_quantity = ccxt_order.get("filled", 0.0)

        # Convert millisecond timestamp to ISO 8601 format [cite: 146, 147]
        timestamp_ms = ccxt_order.get("timestamp")
        iso_timestamp = None
        if timestamp_ms:
            iso_timestamp = datetime.fromtimestamp(
                timestamp_ms / 1000.0, tz=timezone.utc
            ).isoformat()

        return OrderResult(
            success=is_success,
            oid=ccxt_order.get("id"),
            cloid=ccxt_order.get("clientOrderId"),
            status=status,
            symbol=ccxt_order.get("symbol"),
            side=ccxt_order.get("side"),
            price=exec_price or 0.0,
            quantity=filled_quantity,
            timestamp=iso_timestamp,
            message=None
            if is_success
            else "Order status was not 'closed' or 'filled'.",
        )

    # ... (rest of the methods: get_balance, get_order_status, etc.)
    async def get_balance(self) -> Dict[str, float]:
        """
        Fetch account balances from the exchange.

        Returns:
            Dict[str, float]: Dictionary of currency balances
        """
        try:
            balance = await self.exchange.fetch_balance()
            return {
                currency: float(details["total"])
                for currency, details in balance.items()
                if isinstance(details, dict) and "total" in details
            }
        except Exception as e:
            self.logger.error(f"Error fetching balance: {e}")
            return {}

    async def get_order_status(
        self, order_id: str, symbol: str = None
    ) -> Dict[str, Any]:
        """
        Fetch status of an order by ID.

        Args:
            order_id: Exchange-assigned order ID
            symbol: The symbol of the market (e.g., 'BTC/USDT'). Required by some exchanges.

        Returns:
            Dict with order status details
        """
        try:
            # Many exchanges require a symbol to fetch order status [cite: 70]
            order = await self.exchange.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            self.logger.error(f"Error fetching order status for {order_id}: {e}")
            return {"error": str(e)}

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancel an order by ID.

        Args:
            order_id: Exchange-assigned order ID
            symbol: The symbol of the market (e.g., 'BTC/USDT'). Required by some exchanges.

        Returns:
            bool: Success status
        """
        try:
            # Some exchanges may require the symbol to cancel an order
            await self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            self.logger.error(f"Error canceling order {order_id}: {e}")
            return False

    async def subscribe_to_orders(
        self, order_ids: List[str], callback: Callable[[str, Any], None]
    ):
        """
        Subscribe to order status updates via WebSocket (stub).

        Args:
            order_ids: List of order IDs to monitor
            callback: Function to call when status updates arrive
        """
        self.logger.warning("WebSocket order subscription not implemented")
        raise NotImplementedError("WebSocket-based order subscription not implemented")

    async def unsubscribe_to_orders(self, order_ids: List[str]):
        """
        Unsubscribe from order status updates (stub).

        Args:
            order_ids: List of order IDs to stop monitoring
        """
        self.logger.warning("WebSocket order unsubscription not implemented")
        raise NotImplementedError(
            "WebSocket-based order unsubscription not implemented"
        )
