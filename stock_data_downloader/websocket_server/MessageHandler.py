from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Union

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    SIDEMAP,
    ExchangeInterface,
    Order,
)
from stock_data_downloader.websocket_server.portfolio import Portfolio

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
        exchange: ExchangeInterface,
        portfolio: Portfolio,
        simulation_running: bool,
        realtime: bool,
    ) -> HandleResult:
        handle_result = self._send_rejection(data, reason="invalid action")
        action = data.get("action")
        if action == "reset":
            handle_result = HandleResult(result_type=RESET_REQUESTED, payload={})

        elif action in ["final_report", "report"]:
            if simulation_running:
                logging.warning(
                    "Client requested final report while simulation potentially still running?"
                )
            balance_info = await exchange.get_balance()
            final_value = balance_info.get("total_balance", 0)
            if not realtime:
                final_value = portfolio.cash
                total_return = portfolio.calculate_total_return()
                final_portfolio_state = vars(portfolio)
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
            handle_result = await self.handle_order(data["payload"], exchange)
        elif action == "get_order_status":
            order_id_to_query = data.get("order_id")
            if not order_id_to_query:
                handle_result = self._send_rejection(
                    data, reason="Missing order_id for status check."
                )

            try:
                order_status_result = await exchange.get_order_status(
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
                success = await exchange.cancel_order(order_id_to_cancel)
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
        self, data: Dict, exchange: ExchangeInterface
    ) -> HandleResult:
        """Handles incoming messages for placing trade orders."""
        ticker = data.get("ticker", "")
        quantity = data.get("quantity", 0)
        price = data.get("price", 0)
        cloid = data.get("cloid")
        order_type = data.get("order_type")
        timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
        if not ticker or quantity <= 0 or price <= 0 or order_type not in SIDEMAP:
            return self._send_rejection(
                data, reason="Invalid order parameters or unknown action."
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
            order_placement_result = await exchange.place_order(orders_to_place)
            return HandleResult(
                result_type="order_confirmation",
                payload=[vars(result) for result in order_placement_result],
            )

        except Exception as e:
            logging.exception("Error placing order with HyperliquidExchange:")
            return self._send_rejection(data, reason=f"Error placing order: {e}")

    async def process_order_update(
        self, update_data: dict, realtime: bool, portfolio: Portfolio
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
        }
        if not realtime:
            payload["portfolio"] = portfolio
        return HandleResult(result_type=trade_type, payload=payload)

    def _send_execution(
        self,
        websocket,
        data,
        price,
        action_type,
        timestamp,
        realtime,
        portfolio,
        cloid=None,
    ):
        payload = {
            "status": "success",
            "action": action_type,
            "ticker": data["ticker"],
            "quantity": data["quantity"],
            "price": price,
            "portfolio": {},
            "timestamp": (timestamp + timedelta(minutes=1)).isoformat(),
            "cloid": cloid,
        }
        if not realtime:
            payload["portfolio"] = portfolio
        return HandleResult(result_type="trade_execution", payload=payload)

    def _send_rejection(self, data: Dict, reason: str):
        """Standard rejection format"""
        payload = {
            "status": "rejected",
            "order": data,
            "reason": reason,
            "valid_actions": ["buy", "sell", "reset"],
        }
        return HandleResult(result_type="trade_rejection", payload=payload)
