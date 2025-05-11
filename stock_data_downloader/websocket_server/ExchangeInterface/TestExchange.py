import asyncio
from dataclasses import dataclass
import logging
import uuid
from typing import Callable, Dict, Any, List

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface,
    Order,
    OrderResult,
)
from stock_data_downloader.websocket_server.portfolio import Portfolio


logger = logging.getLogger(__name__)


class TestExchange(ExchangeInterface):
    """Test exchange implementation that uses a Portfolio for testing without real market connection"""

    def __init__(self, portfolio: Portfolio, simulation_mode: bool = True):
        """
        Initialize the test exchange

        Args:
            portfolio: Portfolio instance to use for tracking positions and cash
            simulation_mode: Whether to run in simulation mode (vs live mode)
        """
        self.portfolio = portfolio
        self.simulation_mode = simulation_mode
        self.order_callbacks = {}
        self.active_orders = {}
        self.closed_orders = {}
        self.subscription_id_counter = 0
        self.subscription_callbacks = {}
        self.loop = asyncio.get_event_loop()

    async def place_order(self, orders: List[Order]) -> List[OrderResult]:
        """
        Place orders on the test exchange

        Args:
            orders: List of Order objects to execute

        Returns:
            Dict containing order IDs and execution status
        """
        results: List[OrderResult] = []

        for order in orders:
            # Generate a unique order ID
            order_id = str(uuid.uuid4())

            # Normalize the side (BUY, SELL)
            side = order.side.casefold()

            # Execute the order on the portfolio
            success = False
            try:
                if side == "BUY".casefold():
                    success = self.portfolio.buy(
                        order.symbol, order.quantity, order.price
                    )
                elif side == "SELL".casefold():
                    success = self.portfolio.sell(
                        order.symbol, order.quantity, order.price
                    )
                    status = "FILLED"
                # else:
                #     # Handle SHORT and COVER through the portfolio methods
                #     if side == "SHORT".casefold():
                #         self.portfolio.short(order.symbol, order.quantity, order.price)
                #         success = True
                #         status = "FILLED"
                #     elif side == "COVER".casefold():
                #         success = self.portfolio.sell(
                #             order.symbol, order.quantity, order.price
                #         )  # Uses sell to cover short positions
                #         status = "FILLED"
                else:
                    logger.error(f"Unknown order side: {order.side}")
                    status = "REJECTED"
                    
                status = "FILLED" if success else "REJECTED"
                if not success:
                    logging.error(f"{order} failed to execute")

                # Store the order for reference
                order_info = {
                    "id": order_id,
                    "symbol": order.symbol,
                    "side": side,
                    "quantity": order.quantity,
                    "price": order.price,
                    "status": status,
                    "filled_qty": order.quantity if status == "FILLED" else 0,
                    "timestamp": asyncio.get_event_loop().time(),
                    "client_order_id": order.cloid,
                }

                if status == "FILLED":
                    self.closed_orders[order_id] = order_info
                    # Notify any subscribers
                    await self._notify_order_update("order_filled", order_info)
                else:
                    self.active_orders[order_id] = order_info

                results.append(
                    OrderResult(
                        cloid=order.cloid or "",
                        oid=order_id,
                        status=status,
                        price=order.price,
                        quantity=order.quantity,
                        symbol=order.symbol,
                        side=side,
                        success=status == "FILLED",
                        timestamp=order.timestamp,
                    )
                )

                logger.info(
                    f"Order {order_id} {side} {order.quantity} {order.symbol} @ {order.price}: {status}"
                )

            except Exception as e:
                logger.error(f"Error executing order: {e}")
                results.append(
                    OrderResult(
                        cloid=order.cloid or "",
                        oid=order_id,
                        status="ERROR",
                        price=order.price,
                        quantity=order.quantity,
                        symbol=order.symbol,
                        side=side,
                        success=False,
                        timestamp=order.timestamp,
                        message=str(e),
                    )
                )

        return results

    async def get_balance(self) -> Dict[str, float]:
        """
        Get account balances

        Returns:
            Dict with cash balance and positions
        """
        # Calculate the current value of all positions based on the last price
        positions = {}
        for ticker, (qty, avg_price) in self.portfolio.positions.items():
            positions[ticker] = {"quantity": qty, "avg_price": avg_price}

        # Add short positions
        short_positions = {}
        for ticker, (qty, entry_price) in self.portfolio.short_positions.items():
            short_positions[ticker] = {"quantity": qty, "entry_price": entry_price}
        total_balance = self.portfolio.calculate_total_value()
        return {
            "available_balance": self.portfolio.cash,
            "total_balance": total_balance,
            "initial_cash": self.portfolio.initial_cash,
        }

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Check order status by ID

        Args:
            order_id: ID of the order to check

        Returns:
            Order status information
        """
        if order_id in self.active_orders:
            return self.active_orders[order_id]
        elif order_id in self.closed_orders:
            return self.closed_orders[order_id]
        else:
            return {"status": "NOT_FOUND", "order_id": order_id}

    async def subscribe_to_orders(
        self, order_ids: List[str], callback: Callable[[str, Any], None]
    ):
        """
        Subscribe to order updates

        Args:
            order_ids: List of order IDs to subscribe to (empty for all orders)
            callback: Function to call with order updates

        Returns:
            Subscription ID
        """
        subscription_id = self.subscription_id_counter
        self.subscription_id_counter += 1

        self.subscription_callbacks[subscription_id] = {
            "order_ids": order_ids,
            "callback": callback,
        }

        logger.info(f"Subscribed to order updates with ID: {subscription_id}")

    async def unsubscribe_to_orders(self, order_ids: List[str]):
        """
        Unsubscribe from order updates

        Args:
            order_ids: List of order IDs to unsubscribe from
        """
        # Remove matching subscriptions
        to_remove = []
        for sub_id, sub_info in self.subscription_callbacks.items():
            if not order_ids or set(order_ids).intersection(set(sub_info["order_ids"])):
                to_remove.append(sub_id)

        for sub_id in to_remove:
            if sub_id in self.subscription_callbacks:
                del self.subscription_callbacks[sub_id]
                logger.info(f"Unsubscribed from order updates with ID: {sub_id}")

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order by ID

        Args:
            order_id: ID of the order to cancel

        Returns:
            True if canceled, False otherwise
        """
        if order_id in self.active_orders:
            # Update order status
            self.active_orders[order_id]["status"] = "CANCELED"

            # Move to closed orders
            self.closed_orders[order_id] = self.active_orders[order_id]
            del self.active_orders[order_id]

            # Notify subscribers
            await self._notify_order_update(
                "order_canceled", self.closed_orders[order_id]
            )

            logger.info(f"Order {order_id} canceled")
            return True
        else:
            logger.warning(
                f"Cannot cancel order {order_id}: not found or already closed"
            )
            return False

    async def _notify_order_update(self, update_type: str, update_data: Dict[str, Any]):
        """
        Notify all relevant subscribers about an order update

        Args:
            update_type: Type of update (order_filled, order_canceled, etc.)
            update_data: Order data
        """
        order_id = update_data.get("id", "")

        for sub_id, sub_info in self.subscription_callbacks.items():
            order_ids = sub_info["order_ids"]
            callback = sub_info["callback"]

            # If subscription is for all orders or includes this order
            if not order_ids or order_id in order_ids:
                try:
                    # Execute callback in the event loop
                    callback(update_type, update_data)
                except Exception as e:
                    logger.error(
                        f"Error in order update callback (sub_id {sub_id}): {e}"
                    )
