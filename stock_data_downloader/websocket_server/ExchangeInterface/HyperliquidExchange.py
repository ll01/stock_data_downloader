import json
import os
import threading
from typing import Callable, List, Dict, Any, Optional
import eth_account
from hyperliquid.utils import constants
from hyperliquid.exchange import Exchange
from hyperliquid.utils.types import Cloid, OrderUpdatesSubscription
from hyperliquid.utils.signing import  OrderRequest, OrderType
from eth_account.signers.local import LocalAccount
from hyperliquid.websocket_manager import WebsocketManager

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    SIDEMAP,
    ExchangeInterface,
    Order,
)
from stock_data_downloader.websocket_server.thread_cancel_helper import _async_raise, find_threads_by_name



# Define a directory for saving mappings
MAPPING_DIR = "hyperliquid_order_mappings"

class HyperliquidExchange(ExchangeInterface):
    def __init__(
        self, config: Optional[Dict[str, str]] = None, network: str = "mainnet"
    ):
        self.api_keys = config or {}
        if "secret_key" not in self.api_keys:
             raise ValueError("secret_key must be provided in api_keys")

        self.account: LocalAccount = eth_account.Account.from_key(
            self.api_keys["secret_key"]
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
        self._mapping_file = os.path.join(MAPPING_DIR, f"{self.account.address.lower()}.json")

        # Load mapping on initialization
        self._load_mapping()
        self._ws = WebsocketManager(self.base_url)
        self._subscriptions = []


    def _initialize_exchange(self) -> Exchange:
        return Exchange(wallet=self.account, base_url=self.base_url)

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

        with open(self._mapping_file, 'w') as f:
            json.dump(serializable_mapping, f, indent=4)
        # print(f"Order mapping saved to {self._mapping_file}") # Optional logging

    def _load_mapping(self):
        """Loads the internal order mapping from a JSON file."""
        if os.path.exists(self._mapping_file):
            with open(self._mapping_file, 'r') as f:
                try:
                    loaded_mapping = json.load(f)
                    # Convert Cloid raw strings back to Cloid objects
                    for key, value in loaded_mapping.items():
                         if value.get("cloid") is not None:
                              value["cloid"] = Cloid(value["cloid"])
                    self._order_mapping = loaded_mapping
                    # print(f"Order mapping loaded from {self._mapping_file}") # Optional logging
                except json.JSONDecodeError:
                    print(f"Error decoding JSON from {self._mapping_file}. Starting with empty mapping.")
                    self._order_mapping = {}
        else:
            self._order_mapping = {}
            # print(f"No mapping file found at {self._mapping_file}. Starting with empty mapping.") # Optional logging


    async def place_order(self, orders: List[Order]) -> Dict[str, Any]:
        """Place multiple orders atomically (if supported by exchange)."""
        hyperliquid_order_requests: List[OrderRequest] = []
        for order in orders:
            is_buy = SIDEMAP[order.side] == "BUY"
            cloid = Cloid(order.cloid) if order.cloid else None

            # Assuming market orders for simplicity
            order_type: OrderType = {"limit": {"tif": "Ioc"}}

            hyperliquid_order_requests.append({
                "coin": order.symbol,
                "is_buy": is_buy,
                "sz": order.quantity,
                "limit_px": order.price,
                "order_type": order_type,
                "reduce_only": order.args.get("reduce_only", False) if order.args else False,
                "cloid": cloid,
            })

        if not hyperliquid_order_requests:
            return {"status": "no_orders_to_place"}

        order_result = self._exchange.bulk_orders(hyperliquid_order_requests)

        # Process order_result to populate self._order_mapping and save
        if order_result.get("status") == "ok":
            # The response structure for bulk_orders might vary slightly,
            # inspect it to get the exact keys for oid, cloid, and status.
            # Assuming response structure similar to single order result for demonstration
            for status_entry, original_order in zip(order_result.get("response", {}).get("data", {}).get("statuses", []), orders):
                 if status_entry and status_entry.get("status") == "ok": # Check for successful placement
                      # Use cloid if provided, otherwise fall back to oid
                      interface_order_id = original_order.cloid if original_order.cloid else str(status_entry.get("oid"))
                      if interface_order_id: # Ensure we have an ID to map
                           self._order_mapping[interface_order_id] = {
                               "oid": status_entry.get("oid"),
                               "cloid": status_entry.get("cloid"), # Store the cloid if it was sent
                               "ticker": original_order.symbol
                           }
                      # Note: For a robust solution, you might need to handle partial fills or rejections within the bulk response
            self._save_mapping() # Save mapping after updating

        return order_result

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
                    status = self._exchange.info.query_order_by_cloid(self.account.address, order_info["cloid"])
                elif order_info.get("oid") is not None:
                     status = self._exchange.info.query_order_by_oid(self.account.address, int(order_info["oid"]))
                else:
                     return {"order_id": order_id, "status": "mapping_error"}

                # Parse the status response from Hyperliquid
                # The exact keys here depend on the structure returned by query_order_by_oid/cloid
                # You'll need to confirm these by inspecting the SDK response or docs.
                # Assuming a structure where status details are directly in the response dict:
                return {
                    "order_id": order_id,
                    "ticker": ticker,
                    "status": status.get("status", "unknown"), # e.g., "open", "filled", "canceled"
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
                    cancel_result = self._exchange.cancel_by_cloid(ticker, order_info["cloid"])
                elif order_info.get("oid") is not None:
                     cancel_result = self._exchange.cancel(ticker, int(order_info["oid"]))
                else:
                     return False # Should not happen

                # Consider removing the order from the mapping if cancellation is successful
                if cancel_result["status"] == "ok":
                    # Optional: remove from mapping and save
                    # del self._order_mapping[order_id]
                    # self._save_mapping()
                    pass # Decide if you want to remove canceled orders from mapping

                return cancel_result["status"] == "ok"
            except Exception as e:
                print(f"Error canceling order {order_id}: {e}")
                return False
        else:
            # Order not found in internal mapping.
            print(f"Order ID {order_id} not found in internal mapping. Cannot cancel.")
            return False


    async def subscribe_to_orders(self, order_ids: List[str],  callback: Callable[[str, Any], None]):
        """Subscribe to real-time order updates."""
        self._ws.start()
        for thread in [self._ws.ping_sender]:
            if thread and isinstance(thread, threading.Thread) and thread.is_alive():
                thread.daemon = True
        subscription: OrderUpdatesSubscription = {"type": "orderUpdates", "user": self.account.address}
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
        ws_tt = [t for t in threading.enumerate() if  isinstance(t, WebsocketManager)]
       

        for t in ws_tt:
            _async_raise(t.ident, SystemExit)

        ping_threads = find_threads_by_name("send_ping")

        for t in ping_threads:
            _async_raise(t.ident, SystemExit)

    def _round_ammounts(self, value: float, ticker: str, is_quantity: bool = False) -> float:

        if is_quantity:
             # Apply rounding rules for quantity based on szDecimals
             decimals = self.sz_decimals.get(ticker, 0) # Get szDecimals for the ticker
             return round(value, decimals)
        else:
             # Apply rounding rules for price
             max_decimals = 6 # Example value, verify with Hyperliquid specs
             if value > 100_000:
                  return round(value)
             else:
                  # This part of the original logic seems specific to price and szDecimals interaction
                  # Verify if this is the correct way to round price on Hyperliquid
                  decimals = max_decimals - self.sz_decimals.get(ticker, 0)
                  return round(float(f"{value:.5g}"), decimals)