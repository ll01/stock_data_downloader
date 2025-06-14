from datetime import datetime, timezone
import json
import logging
import os
import threading
import time
from typing import Callable, List, Dict, Any, Optional
import eth_account
from hyperliquid.utils import constants
from hyperliquid.exchange import Exchange
from hyperliquid.utils.types import Cloid, OrderUpdatesSubscription
from hyperliquid.utils.signing import OrderRequest, OrderType
from eth_account.signers.local import LocalAccount
from hyperliquid.websocket_manager import WebsocketManager

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface,
)
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult
from stock_data_downloader.websocket_server.thread_cancel_helper import (
    _async_raise,
    find_threads_by_name,
)
from stock_data_downloader.websocket_server.portfolio import Portfolio


# Define a directory for saving mappings
MAPPING_DIR = "hyperliquid_order_mappings"


class HyperliquidExchange(ExchangeInterface):
    def __init__(
        self, config: Optional[Dict[str, str]] = None, network: str = "mainnet"
    ):
        self.config = config or {}
        if "secret_key" not in self.config:
            raise ValueError("secret_key must be provided in api_keys")
        self.fetch_status_after_order = self.config.get("fetch_status_after_order", True)
        
        if "wallet_address" not in self.config:
            raise ValueError("wallet_addresss must be provided in config")
        self.wallet_address  = self.config["wallet_address"]
        
        # Initialize portfolio
        self._portfolio = Portfolio(initial_cash=0)




        self.account: LocalAccount = eth_account.Account.from_key(
            self.config["secret_key"]
        )
        self.base_url = (
            constants.TESTNET_API_URL
            if network == "testnet"
            else constants.MAINNET_API_URL
        )
        self._exchange: Exchange = self._initialize_exchange()
        self.meta = self._initialize_metadata()
        self.sz_decimals = self._initialize_sz_decimals()

        # Internal mapping for order_id -> {oid, cloid, ticker}
        self._order_mapping: Dict[str, Dict[str, Any]] = {}
        self._mapping_file = os.path.join(
            MAPPING_DIR, f"{self.account.address.lower()}.json"
        )

        # Load mapping on initialization
        self._load_mapping()
        self._ws = WebsocketManager(self.base_url)
        self._subscriptions = []

    def _initialize_exchange(self) -> Exchange:
        return Exchange(wallet=self.account, base_url=self.base_url)
        
    @property
    def portfolio(self) -> Portfolio:
        """Return the portfolio associated with this exchange"""
        return self._portfolio

    def _initialize_metadata(self):
        return self._exchange.info.meta()

    def _initialize_sz_decimals(self):
        sz_decimals = {}
        for asset_info in self.meta["universe"]:
            sz_decimals[asset_info["name"]] = asset_info["szDecimals"]
        return sz_decimals

    def _save_mapping(self):
        """Saves the internal order mapping to a JSON file."""
        os.makedirs(MAPPING_DIR, exist_ok=True)
        # Prepare mapping for serialization, converting Cloid objects
        serializable_mapping = {}
        for key, value in self._order_mapping.items():
            serializable_value = value.copy()
            if isinstance(serializable_value.get("cloid"), Cloid):
                serializable_value["cloid"] = serializable_value["cloid"].to_raw()
            serializable_mapping[key] = serializable_value

        with open(self._mapping_file, "w") as f:
            json.dump(serializable_mapping, f, indent=4)
        # print(f"Order mapping saved to {self._mapping_file}") # Optional logging

    def _load_mapping(self):
        """Loads the internal order mapping from a JSON file."""
        if os.path.exists(self._mapping_file):
            with open(self._mapping_file, "r") as f:
                try:
                    loaded_mapping = json.load(f)
                    # Convert Cloid raw strings back to Cloid objects
                    for key, value in loaded_mapping.items():
                        if value.get("cloid") is not None:
                            value["cloid"] = Cloid(value["cloid"])
                    self._order_mapping = loaded_mapping
                    # print(f"Order mapping loaded from {self._mapping_file}") # Optional logging
                except json.JSONDecodeError:
                    print(
                        f"Error decoding JSON from {self._mapping_file}. Starting with empty mapping."
                    )
                    self._order_mapping = {}
        else:
            self._order_mapping = {}
            # print(f"No mapping file found at {self._mapping_file}. Starting with empty mapping.") # Optional logging


    async def place_order(self, orders: List[Order]) -> List[OrderResult]:
        """Place multiple orders independently. Failures won’t stop the rest."""
        output: List[OrderResult] = []

        for order in orders:
            # Build the Hyperliquid request payload
            is_buy = order.side == "BUY".casefold()
            quantity = self._round_ammounts(order.quantity, order.symbol, is_quantity=True)
            price = self._round_ammounts(order.price, order.symbol, is_quantity=False)
           
            cloid_obj = Cloid(order.cloid) if order.cloid else None

            try:
                # Send just this one order
                raw = self._exchange.market_open(order.symbol, is_buy, quantity, None, cloid=cloid_obj)
                # bulk_orders returns a dict with statuses under response.data.statuses[0]
                status_entry = raw["response"]["data"]["statuses"][0]

                # Only map & save if this particular order succeeded
                id_data = status_entry.get("filled") or status_entry.get("resting")
                if raw.get("status") == "ok" and id_data:
                    interface_id = order.cloid or str(status_entry["oid"])
                    self._order_mapping[interface_id] = {
                        "oid": id_data.get("oid"),
                        "cloid": id_data.get("cloid"),
                        "ticker": order.symbol,
                    }
                    self._save_mapping()

                # Normalize into your dataclass
                output.append(self.place_order_standardized(raw, cloid_obj))

            except Exception as exc:
                logging.error(f"[place_order] failed for cloid={order.cloid}: {exc}", exc_info=True)
                
                # For failed orders, set position_change and cash_impact to 0
                result = OrderResult(
                    cloid=order.cloid or "",
                    oid="",
                    status="error",
                    side=order.side,
                    price=price,
                    quantity=quantity,
                    symbol=order.symbol,
                    success=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=str(exc),
                )
                output.append(result)

                # Return a “failure” OrderResult for this one
                output.append(OrderResult(
                    cloid=order.cloid or "",
                    oid="",
                    status="error",
                    side=order.side,
                    price=price,
                    quantity=quantity,
                    symbol=order.symbol,
                    success=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=str(exc),
                ))

        return output

    
    
    def place_order_standardized(self, raw: Dict, cloid: Optional[Cloid]) -> OrderResult:
        """
        Converts the raw Hyperliquid order response to a standardized OrderResult.
        Optionally queries latest status if configured.
        """
        success = raw.get("status") == "ok"
        status_data = raw["response"]["data"]["statuses"][0]

        # Determine which status key is present: e.g., 'resting', 'filled'
        key = next(iter(status_data))
        details = status_data[key]

        oid: int = details["oid"]
        qty = float(details.get("totalSz", details.get("sz", 0)))
        avg_px = float(details.get("avgPx", details.get("limitPx", 0)))

        # Fallback values in case fetch_status_after_order is False or fails
        symbol = details.get("coin", "unknown")
        price = avg_px
        timestamp = datetime.now(timezone.utc).isoformat()
        side = "unknown"

        if self.fetch_status_after_order and success:
            try:
                if cloid:
                    order_info = self._exchange.info.query_order_by_cloid(self.wallet_address, cloid)
                else:
                    order_info = self._exchange.info.query_order_by_oid(self.wallet_address, oid)
        

                metadata = order_info.get("order", {})
                order_metadata = metadata.get("order", {})

                symbol = order_metadata.get("coin", symbol)
                price = float(order_metadata.get("limitPx", price))
                side_code = order_metadata.get("side", "").casefold()
                side = "buy" if side_code == "b" else "sell" if side_code == "a" else "unknown"
                ts = metadata.get("statusTimestamp")
                if ts:
                    timestamp = datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()
            except Exception as e:
                logging.warning(f"Failed to fetch post-order status for oid={oid}: {e}")

        return OrderResult(
            cloid=cloid.to_raw() if cloid else "",
            oid=str(oid),
            status=key,
            price=price,
            quantity=qty,
            symbol=symbol,
            side=side,
            success=success,
            timestamp=timestamp,
        )

           

    async def get_balance(self) -> Dict[str, float]:
        """Fetch account balances."""
        info = self._exchange.info.user_state(self.account.address)
        return {
            "available_balance": float(info.get("freeCollateral", 0)),
            "total_balance": float(info.get("accountValue", 0)),
        }

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Check status of a single order."""
        order_info = self._order_mapping.get(order_id)

        if order_info:
            ticker = order_info["ticker"]
            try:
                if order_info.get("cloid"):
                    # Hyperliquid's query_order_by_cloid expects the Cloid object
                    status = self._exchange.info.query_order_by_cloid(
                        self.account.address, order_info["cloid"]
                    )
                elif order_info.get("oid") is not None:
                    status = self._exchange.info.query_order_by_oid(
                        self.account.address, int(order_info["oid"])
                    )
                else:
                    return {"order_id": order_id, "status": "mapping_error"}

                # Parse the status response from Hyperliquid
                # The exact keys here depend on the structure returned by query_order_by_oid/cloid
                # You'll need to confirm these by inspecting the SDK response or docs.
                # Assuming a structure where status details are directly in the response dict:
                return {
                    "order_id": order_id,
                    "ticker": ticker,
                    "status": status.get(
                        "status", "unknown"
                    ),  # e.g., "open", "filled", "canceled"
                    "filled_qty": float(status.get("cumulativeFilled", 0)),
                    "avg_price": float(status.get("averageFilledPrice", 0)),
                }
            except Exception as e:
                print(f"Error querying order status for {order_id}: {e}")
                # Fallback or return an error status
                return {"order_id": order_id, "status": "query_failed"}
        else:
            # Order not found in internal mapping.
            # You could attempt to fetch open orders from the exchange as a fallback,
            # but for simplicity, we'll return unknown here.
            print(f"Order ID {order_id} not found in internal mapping.")
            return {"order_id": order_id, "status": "unknown"}

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order."""
        order_info = self._order_mapping.get(order_id)

        if order_info:
            ticker = order_info["ticker"]
            try:
                if order_info.get("cloid"):
                    # Hyperliquid's cancel_by_cloid expects the Cloid object
                    cancel_result = self._exchange.cancel_by_cloid(
                        ticker, order_info["cloid"]
                    )
                elif order_info.get("oid") is not None:
                    cancel_result = self._exchange.cancel(
                        ticker, int(order_info["oid"])
                    )
                else:
                    return False  # Should not happen

                # Consider removing the order from the mapping if cancellation is successful
                if cancel_result["status"] == "ok":
                    # Optional: remove from mapping and save
                    # del self._order_mapping[order_id]
                    # self._save_mapping()
                    pass  # Decide if you want to remove canceled orders from mapping

                return cancel_result["status"] == "ok"
            except Exception as e:
                print(f"Error canceling order {order_id}: {e}")
                return False
        else:
            # Order not found in internal mapping.
            print(f"Order ID {order_id} not found in internal mapping. Cannot cancel.")
            return False

    async def subscribe_to_orders(
        self, order_ids: List[str], callback: Callable[[str, Any], None]
    ):
        """Subscribe to real-time order updates."""
        self._ws.start()
        for thread in [self._ws.ping_sender]:
            if thread and isinstance(thread, threading.Thread) and thread.is_alive():
                thread.daemon = True
        subscription: OrderUpdatesSubscription = {
            "type": "orderUpdates",
            "user": self.account.address,
        }
        sub_id = self._ws.subscribe(subscription, callback=callback)
        self._subscriptions.append(
            (
                subscription,
                sub_id,
            )
        )

    async def unsubscribe_to_orders(self, order_ids: List[str]):
        """Unsubscribe from real-time data."""
        # 1) unsubscribe all WS subscriptions
        for sub, sub_id in self._subscriptions:
            self._exchange.info.unsubscribe(sub, sub_id)
        self._subscriptions.clear()
        self._callback = None

        # 2) stop the ping loop and the WebSocketApp
        self._ws.stop()
        self._ws.ws.close()
        self._ws.ws.keep_running = False

        # 3) wait for ping_sender to fully exit
        if self._ws.ping_sender.is_alive():
            self._ws.ping_sender.join()

        # 4) wait for the WebsocketManager thread to finish
        if self._ws.is_alive():
            self._ws.join()

        # 5) clean up
        del self._ws
        ws_tt = [t for t in threading.enumerate() if isinstance(t, WebsocketManager)]

        for t in ws_tt:
            _async_raise(t.ident, SystemExit)

        ping_threads = find_threads_by_name("send_ping")

        for t in ping_threads:
            _async_raise(t.ident, SystemExit)

    def _round_ammounts(
        self, value: float, ticker: str, is_quantity: bool = False
    ) -> float:
        if is_quantity:
            # Apply rounding rules for quantity based on szDecimals
            decimals = self.sz_decimals.get(ticker, 0)  # Get szDecimals for the ticker
            return round(value, decimals)
        else:
            # Apply rounding rules for price
            max_decimals = 6  # Example value, verify with Hyperliquid specs
            if value > 100_000:
                return round(value)
            else:
                # This part of the original logic seems specific to price and szDecimals interaction
                # Verify if this is the correct way to round price on Hyperliquid
                decimals = max_decimals - self.sz_decimals.get(ticker, 0)
                return round(float(f"{value:.5g}"), decimals)


class RobustWebsocketClient:
    def __init__(self, base_url, subscribe_payload, callback, reconnect_interval=5):
        self.base_url = base_url
        self.subscribe_payload = subscribe_payload
        self.callback = callback
        self.reconnect_interval = reconnect_interval
        self._ws = None
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="ws_reconnector", daemon=True)
        self._thread.start()

    def _run_loop(self):
        while self._running:
            try:
                self._ws = WebsocketManager(self.base_url)
                self._ws.start()
                sub_id = self._ws.subscribe(self.subscribe_payload, callback=self.callback)
                logging.info(f"[WS] Subscribed with ID {sub_id}")
                while self._ws.is_alive():
                    time.sleep(1)
                raise Exception("WebSocket thread died")
            except Exception as e:
                logging.warning(f"[WS] Disconnected or failed: {e}. Reconnecting in {self.reconnect_interval}s")
                time.sleep(self.reconnect_interval)

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join()