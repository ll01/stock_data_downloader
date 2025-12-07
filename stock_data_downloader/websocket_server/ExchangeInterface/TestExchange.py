import asyncio
import logging
import uuid
import random
import math
from typing import Awaitable, Callable, Dict, Any, List

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface,
)
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult
from stock_data_downloader.websocket_server.portfolio import Portfolio


logger = logging.getLogger(__name__)


class TestExchange(ExchangeInterface):
    __test__ = False  # Prevent pytest from collecting this as a test case
    order_cls = Order
    """Test exchange implementation that uses a Portfolio for testing without real market connection"""

    def __init__(self, portfolio: Portfolio, maker_fee_bps: float = 0.0, taker_fee_bps: float = 5.0, slippage_bps: float = 0.0, slippage_model: str = "fixed", slippage_variability_bps: float = 0.0):
        """
        Initialize the test exchange

        Args:
            portfolio: Portfolio instance to use for tracking positions and cash
            simulation_mode: Whether to run in simulation mode (vs live mode)
        """

        self.order_callbacks = {}
        self.active_orders = {}
        self.closed_orders = {}
        self.subscription_id_counter = 0
        self.subscription_callbacks = {}
        self.portfolio = portfolio
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.slippage_bps = slippage_bps
        self.slippage_model = slippage_model
        self.slippage_variability_bps = slippage_variability_bps
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:  # No running event loop
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

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

            # Normalize the side (BUY, SELL, SHORT, COVER)
            side = order.side.casefold()

            # Execute the order on the portfolio
            success = False
            try:
                if side in ["buy", "sell"]:
                    status = "FILLED"
                    success = True
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
                else:
                    self.active_orders[order_id] = order_info

                adjusted_price = order.price
                
                # Calculate slippage factor based on model
                slippage_factor = 0.0
                
                if self.slippage_model == "normal":
                    # Sample from normal distribution
                    # Mean = slippage_bps, StdDev = slippage_variability_bps
                    # We divide by 10000.0 to convert basis points to decimal factor
                    mean_slippage = self.slippage_bps
                    std_dev = self.slippage_variability_bps
                    sampled_bps = random.normalvariate(mean_slippage, std_dev)
                    # Slippage is usually against you: buy higher, sell lower
                    slippage_factor = sampled_bps / 10000.0
                else: 
                    # Fixed slippage model (default)
                    slippage_factor = self.slippage_bps / 10000.0
                
                if side == "buy":
                    adjusted_price = order.price * (1 + slippage_factor)
                elif side == "sell":
                    # For selling, slippage means we sell for less
                    adjusted_price = order.price * (1 - slippage_factor)

                # Apply fees
                slippage_adjusted_price = adjusted_price
                if side == "buy":
                    adjusted_price = slippage_adjusted_price * (1 + self.taker_fee_bps / 10000.0)
                    fee_paid = order.quantity * slippage_adjusted_price * (self.taker_fee_bps / 10000.0)
                elif side == "sell":
                    adjusted_price = slippage_adjusted_price * (1 - self.taker_fee_bps / 10000.0)
                    fee_paid = order.quantity * slippage_adjusted_price * (self.taker_fee_bps / 10000.0)
                else:
                    fee_paid = 0.0

                results.append(
                    OrderResult(
                        cloid=order.cloid or "",
                        oid=order_id,
                        status=status,
                        price=adjusted_price,
                        quantity=order.quantity,
                        symbol=order.symbol,
                        side=side,
                        success=status == "FILLED",
                        timestamp=order.timestamp,
                        fee_paid=fee_paid,
                    )
                )

                logger.info(
                    f"Order {order_id} {side} {order.quantity} {order.symbol} @ {adjusted_price}: {status}"
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
        self, order_ids: List[str], callback: Callable[[str, Any], Awaitable[None]]
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
            callback = sub_info["callback"]
            
            try:
                # Execute callback in the event loop
                await callback(update_type, update_data)
            except Exception as e:
                logger.error(
                    f"Error in order update callback (sub_id {sub_id}): {e}"
                )
            
