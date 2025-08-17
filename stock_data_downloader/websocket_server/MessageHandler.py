import copy
import json
import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Union

from stock_data_downloader.models import TickerData
from stock_data_downloader.websocket_server.DataSource.BarResponse import BarResponse

from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.trading_system import TradingSystem

RESET_REQUESTED = "reset"
FINAL_REPORT_REQUESTED = "final_report"
TRADE_REJECTION = "trade_rejection"  # Use a constant for rejection type
ORDER_CONFIRMATION = "order_confirmation"
ORDER_STATUS_REPORT = "order_status"
ORDER_CANCELLATION_REPORT = "order_cancellation"
ACCOUNT_BALANCE_REPORT = "account_balance"


@dataclass
class HandleResult:
    result_type: str
    payload: Union[Dict, List[Dict], List[TickerData]]


class MessageHandler:
    async def handle_message(
        self,
        raw_data: Union[Dict, str],
        trading_system: TradingSystem,
        connection_manager: ConnectionManager,
    ) -> HandleResult:
        # Handle JSON parsing if raw_data is a string
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                return HandleResult(
                    result_type="error",
                    payload={
                        "status": "error",
                        "code": "INVALID_JSON",
                        "message": "Invalid JSON format received",
                    },
                )
        else:
            data = raw_data

        handle_result = self._send_rejection(data, reason="invalid action")
        action = data.get("action")
        logging.debug(action)
        if action == "reset":
            # When reset is requested, we need to actually perform the reset operation
            try:
                # Reset the data source (support sync or async implementations)
                if hasattr(trading_system, 'data_source') and trading_system.data_source:
                    reset_res = trading_system.data_source.reset()
                    # Some implementations may return an awaitable/coroutine - await if so
                    if inspect.isawaitable(reset_res) or asyncio.iscoroutine(reset_res):
                        await reset_res

                # Reset the portfolio
                if hasattr(trading_system, 'portfolio') and trading_system.portfolio:
                    trading_system.portfolio.clear_positions()
                
                # Clear the final report sent flag for this client (only if we have a valid client id)
                websocket = data.get("_ws") if isinstance(data, dict) else None
                if websocket:
                    client_id = connection_manager.get_client_id(websocket)
                    if client_id is not None and hasattr(connection_manager, '_final_report_sent'):
                        connection_manager._final_report_sent.discard(client_id)
                
                logging.info("Server simulation reset completed")
                handle_result = HandleResult(result_type=RESET_REQUESTED, payload={"message": "Simulation reset completed"})
            except Exception as e:
                logging.exception(f"Error during reset: {e}")
                handle_result = HandleResult(
                    result_type="error",
                    payload={
                        "status": "error",
                        "code": "RESET_FAILED",
                        "message": f"Failed to reset simulation: {str(e)}",
                    },
                )

        elif action == "next_bar":
            # Per-client stepping: accept either a client_id (preferred) or websocket (legacy)
            client_id = data.get("_client_id")
            websocket = data.get("_ws")
            if not client_id:
                if websocket is None:
                    return self._send_rejection(
                        data, reason="Missing websocket context for next_bar"
                    )
                client_id = connection_manager.get_client_id(websocket)
            if not client_id:
                return self._send_rejection(data, reason="Unknown client for next_bar")
    
            # Per-client stepping: call the interface method and expect a BarResponse.
            ds = getattr(trading_system, "data_source", None)
            if ds is None:
                return self._send_rejection(data, reason="No data source available")
    
            try:
                maybe = ds.get_next_bar_for_client(client_id)
                # Support both sync and async implementations
                if asyncio.iscoroutine(maybe) or hasattr(maybe, "__await__"):
                    bar_resp = await maybe
                else:
                    bar_resp = maybe
            except Exception as e:
                logging.exception(f"Error retrieving next bar for client {client_id}: {e}")
                return HandleResult(
                    result_type="simulation_end",
                    payload={"reason": str(e)},
                )
    
            # Backwards compatibility: some tests/implementations may still return a plain list
            if isinstance(bar_resp, list):
                if not bar_resp:
                    return HandleResult(
                        result_type="simulation_end",
                        payload={"reason": "End of backtest simulation reached."},
                    )
                return HandleResult(result_type="price_update", payload=bar_resp)
    
            # Expect a BarResponse-like object
            data_list = getattr(bar_resp, "data", None)
            error_msg = getattr(bar_resp, "error_message", None)
    
            if error_msg:
                return HandleResult(
                    result_type="simulation_end",
                    payload={"reason": str(error_msg)},
                )
    
            if not data_list:
                return HandleResult(
                    result_type="simulation_end",
                    payload={"reason": "End of backtest simulation reached."},
                )
    
            return HandleResult(result_type="price_update", payload=data_list)
        elif action in ["final_report", "report"]:
            # Check if we've already sent a final report for this client
            websocket = raw_data.get("_ws") if isinstance(raw_data, dict) else None
            if websocket:
                client_id = connection_manager.get_client_id(websocket)
                # Only proceed if we have a concrete client_id (not None)
                if client_id is not None:
                    if hasattr(connection_manager, '_final_report_sent'):
                        if client_id in connection_manager._final_report_sent:
                            # Already sent final report, don't send again
                            return HandleResult(
                                result_type="error",
                                payload={
                                    "status": "error",
                                    "code": "FINAL_REPORT_ALREADY_SENT",
                                    "message": "Final report already sent for this simulation",
                                },
                            )
                        else:
                            # Mark that we've sent the final report
                            connection_manager._final_report_sent.add(client_id)
                    else:
                        connection_manager._final_report_sent = {client_id}
            
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
            handle_result = await self.handle_order(data["data"], trading_system)
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
            else:
                logging.warning(f"unrecognized action {action} full message {data}")
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
            payload = []
            for result in order_placement_result:
                if result.success:
                    trading_system.portfolio.apply_order_result(result)
                    result_dict = vars(result)
                    result_dict["portfolio"] = vars(trading_system.portfolio)
                    payload.append(result_dict)
            return HandleResult(result_type="order_confirmation", payload=payload)

        except Exception as e:
            logging.exception("Error placing order with HyperliquidExchange:")
            return self._send_rejection(data, reason=f"Error placing order: {e}")

    async def process_order_update(self, update_data: dict, portfolio: Portfolio):
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
            "portfolio": portfolio,
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
        """Standard rejection format with field-level errors.

        This function removes internal-only fields (like the live websocket
        object under the '_ws' key or internal client id under '_client_id')
        before returning the payload so we don't leak non-serializable or
        sensitive objects back to clients.
        """
        sanitized_order = dict(data)
        # remove internal runtime objects before returning to client
        sanitized_order.pop("_ws", None)
        sanitized_order.pop("_client_id", None)
        payload = {
            "status": "rejected",
            "order": sanitized_order,
            "reason": reason,
            "valid_actions": ["buy", "sell", "reset"],
            "field": field or "unknown",
        }
        return HandleResult(result_type=TRADE_REJECTION, payload=payload)
