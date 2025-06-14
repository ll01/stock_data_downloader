import logging
from typing import List, Dict, Any, Callable, Optional

import ccxt.async_support as ccxt

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import ExchangeInterface
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order  


class CCTXExchange(ExchangeInterface):
    """
    Implementation of ExchangeInterface using CCXT async support.
    Supports market orders, balance checks, and order status/cancellation.
    """

    def __init__(
        self,
        config: dict
      
    ):
        """
        Initialize the exchange instance.

        Args:
            api_key: API key for the exchange
            api_secret: API secret for authentication
            exchange_id: Identifier for the exchange (e.g., 'binance')
            sandbox: Use sandbox/testnet if True
            password: Optional password for exchanges like Binance
            **kwargs: Additional exchange-specific configuration
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        exchange_id  = config['exchange_id']
        exchange_class = getattr(ccxt, exchange_id, None)

        if not exchange_class:
            raise ValueError(f"Exchange {exchange_id} not supported by CCXT")
        
        ccxt_params = {
            "apiKey": config.get("api_key", ""),
            "secret": config.get("api_secret", ""),
            "enableRateLimit": config.get("enableRateLimit", True),
            "sandbox": config.get("sandbox", False),
            "password": config.get("password", None),
            "options": config.get("options", {}),  # Use for exchange-specific settings
        }
        self.exchange = exchange_class(ccxt_params)


    async def place_order(self, orders: List[Order]) -> Dict[str, Any]:
        """
        Place one or more market orders on the exchange.

        Args:
            orders: List of Order objects to execute

        Returns:
            Dict with results of each order placement
        """
        results = []
        for order in orders:
            try:
                params = {}
                if order.cloid:
                    params['clientOrderId'] = order.cloid
                if order.args:
                    params.update(order.args)

                ccxt_side = order.side.lower()
                symbol = order.symbol
                amount = order.quantity
                price = order.price if order.price else None

                response = await self.exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side=ccxt_side,
                    amount=amount,
                    price=price,
                    params=params
                )
                results.append(response)
            except Exception as e:
                self.logger.error(f"Error placing order {order}: {e}")
                results.append({'error': str(e)})

        return {'results': results}

    async def get_balance(self) -> Dict[str, float]:
        """
        Fetch account balances from the exchange.

        Returns:
            Dict[str, float]: Dictionary of currency balances
        """
        try:
            balance = await self.exchange.fetch_balance()
            return {
                currency: float(details['total'])
                for currency, details in balance.items()
                if isinstance(details, dict) and 'total' in details
            }
        except Exception as e:
            self.logger.error(f"Error fetching balance: {e}")
            return {}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Fetch status of an order by ID.

        Args:
            order_id: Exchange-assigned order ID

        Returns:
            Dict with order status details
        """
        try:
            # Some exchanges require a symbol to fetch order status
            # If symbol is missing, this may raise an error
            order = await self.exchange.fetch_order(order_id)
            return order
        except Exception as e:
            self.logger.error(f"Error fetching order status for {order_id}: {e}")
            return {'error': str(e)}

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order by ID.

        Args:
            order_id: Exchange-assigned order ID

        Returns:
            bool: Success status
        """
        try:
            result = await self.exchange.cancel_order(order_id)
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
        raise NotImplementedError("WebSocket-based order unsubscription not implemented")