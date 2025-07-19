from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Union

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface,
)
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.trading_system import TradingSystem

RESET_REQUESTED = "reset_requested"
FINAL_REPORT_REQUESTED = "final_report_requested"
TRADE_REJECTION = "trade_rejection"  # Use a constant for rejection type
ORDER_CONFIRMATION = "order_confirmation"
ORDER_STATUS_REPORT = "order_status"
ORDER_CANCELLATION_REPORT = "order_cancellation"
ACCOUNT_BALANCE_REPORT = "account_balance"


@dataclass
class HandleResult:
    result_type: str
    payload: Union[Dict, List[Dict]]


class MessageHandler:
    async def handle_message(
        self,
        data: Dict[str, Any],
        trading_system: TradingSystem,
    ) -> HandleResult:
        handle_result = self._send_rejection(data, reason="invalid action")
        action = data.get("action")
        if action == "reset":
            handle_result = HandleResult(result_type=RESET_REQUESTED, payload={})

        elif action in ["final_report", "report"]:
            balance_info = await trading_system.exchange.get_balance()
            final_value = balance_info.get("total_balance", 0)
            if trading_system.portfolio:
                final_value = trading_system.portfolio.cash
                total_return = trading_system.portfolio.calculate_total_return()
                final_portfolio_state = vars(trading_system.portfolio)
                payload = {
                    "final_value": final_value,
                    "total_return": total_return,
                    "portfolio": final_portfolio_state,  # Send the final state
                    "timestamp": datetime.now().isoformat(),
                }
            else:
                payload = {
                    "final_value": final_value,
                }

            handle_result = HandleResult(result_type="final_report", payload=payload)
        elif action == "order":
            handle_result = await self.handle_order(
                data["data"], trading_system
            )
        elif action == "get_order_status":
            order_id_to_query = data.get("order_id")
            if not order_id_to_query:
                handle_result = self._send_rejection(
                    data, reason="Missing order_id for status check."
                )

            try:
                order_status_result = await trading_system.exchange.get_order_status(
                    str(order_id_to_query)
                )
                handle_result = HandleResult(
                    result_type="order_status", payload=order_status_result
                )

            except Exception as e:
                logging.exception(
                    f"Error getting order status for {order_id_to_query}:"
                )
                handle_result = HandleResult(
                    result_type="order_status",
                    payload={
                        "order_id": order_id_to_query,
                        "status": "error",
                        "message": f"Failed to get status: {e}",
                    },
                )

        elif action == "cancel_order":
            order_id_to_cancel = str(data.get("order_id"))
            if not order_id_to_cancel:
                handle_result = self._send_rejection(
                    data, reason="Missing order_id for cancellation."
                )
            try:
                success = await trading_system.exchange.cancel_order(order_id_to_cancel)
                if success:
                    handle_result = HandleResult(
                        result_type="order_cancellation",
                        payload={"order_id": order_id_to_cancel, "status": "success"},
                    )
                else:
                    handle_result = HandleResult(
                        result_type="order_cancellation",
                        payload={
                            "order_id": order_id_to_cancel,
                            "status": "failed",
                            "message": "Cancellation request failed or order not found.",
                        },
                    )
            except Exception as e:
                logging.exception(f"Error canceling order {order_id_to_cancel}:")
                handle_result = HandleResult(
                    result_type="order_cancellation",
                    payload={
                        "order_id": order_id_to_cancel,
                        "status": "error",
                        "message": f"Error canceling order: {e}",
                    },
                )
        return handle_result

    async def handle_order(
        self, data: Dict, trading_system: TradingSystem
    ) -> HandleResult:
        """Handles incoming messages for placing trade orders."""
        ticker = data.get("ticker", "")
        quantity = data.get("quantity", 0)
        price = data.get("price", 0)
        cloid = data.get("cloid")
        order_type = data.get("order_type", "")
        timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
        if not ticker:
            return self._send_rejection(
                data, reason="Missing required field: ticker", field="ticker"
            )
        if quantity <= 0:
            return self._send_rejection(
                data, reason="Quantity must be a positive number", field="quantity"
            )
        if price <= 0:
            return self._send_rejection(
                data, reason="Price must be a positive number", field="price"
            )

        orders_to_place = [
            Order(
                symbol=ticker,
                side=order_type,
                quantity=quantity,
                price=price,
                cloid=cloid,
                args={},
                timestamp=timestamp,
            )
        ]

        try:
            order_placement_result = await trading_system.exchange.place_order(
                orders_to_place
            )
            for result in order_placement_result:
                if result.success:
                    trading_system.portfolio.apply_order_result(result)
            return HandleResult(
                result_type="order_confirmation",
                payload=[vars(result) for result in order_placement_result],
            )

        except Exception as e:
            logging.exception("Error placing order with HyperliquidExchange:")
            return self._send_rejection(data, reason=f"Error placing order: {e}")

    async def process_order_update(
        self, update_data: dict,  portfolio: Portfolio
    ):
        logging.debug(f"Received order update: {update_data}")

        order = update_data.get("order", {})
        status = update_data.get("status")
        trade_type = "trade_partial"
        if status == "filled":
            trade_type = "trade_execution"
        if status in ["rejected", "marginCanceled", "canceled"]:
            trade_type = "trade_rejection"

        payload = {
            "status": "success",
            "ticker": order.get("coin"),
            "current_quantity": order.get("sz"),
            "requested_quantity": order.get("origSz"),
            "price": order.get("limitPx"),
            "timestamp": order.get("statusTimestamp"),
            "cloid": order.get("cloid", ""),
            "exchange_id": order.get("oid", ""),
            "portfolio": portfolio
        }
        return HandleResult(result_type=trade_type, payload=payload)

    def _send_execution(
        self,
        websocket,
        data,
        price,
        action_type,
        timestamp,
        portfolio,
        cloid=None,
    ):
        """
        Send trade execution confirmation with unified handling.
        
        This method provides consistent trade execution responses
        regardless of data source type.
        """
        payload = {
            "status": "success",
            "action": action_type,
            "ticker": data["ticker"],
            "quantity": data["quantity"],
            "price": price,
            "portfolio": portfolio,  # Always include portfolio information
            "timestamp": (timestamp + timedelta(minutes=1)).isoformat(),
            "cloid": cloid,
        }
        return HandleResult(result_type="trade_execution", payload=payload)

    def _send_rejection(self, data: Dict, reason: str, field: str | None = None):
        """Standard rejection format with field-level errors"""
        payload = {
            "status": "rejected",
            "order": data,
            "reason": reason,
            "valid_actions": ["buy", "sell", "reset"],
            "field": field or "unknown",
        }
        return HandleResult(result_type="trade_rejection", payload=payload)
