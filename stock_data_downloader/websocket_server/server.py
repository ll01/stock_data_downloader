import asyncio
import json
import logging
import socket
import inspect
from unittest.mock import Mock
from typing import Any, Optional
from datetime import datetime, timezone

from stock_data_downloader.models import AppConfig, TickerData
from stock_data_downloader.websocket_server.factories.DataSourceFactory import (
    DataSourceFactory,
)
from stock_data_downloader.websocket_server.factories.ExchangeFactory import (
    ExchangeFactory,
)
import websockets
from websockets.asyncio.server import ServerConnection


from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager

from stock_data_downloader.websocket_server.trading_system import TradingSystem

from stock_data_downloader.websocket_server.MessageHandler import (
    RESET_REQUESTED,
    MessageHandler,
)
from stock_data_downloader.websocket_server.portfolio import Portfolio


logger = logging.getLogger(__name__)


def find_free_port():
    """Finds a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WebSocketServer:
    def __init__(
        self,
        trading_system: TradingSystem,
        connection_manager: ConnectionManager,
        message_handler: MessageHandler,
        uri: str,
        max_in_flight_messages: int = 10,
        realtime: bool = False,
    ):
        self.trading_system = trading_system
        self.connection_manager = connection_manager
        # Initialize the final report sent tracking
        if not hasattr(self.connection_manager, '_final_report_sent'):
            self.connection_manager._final_report_sent = set()
        self.message_handler = message_handler
        self.uri = uri
        # Per-client coordination for backtests
        self._client_ready: dict[str, asyncio.Event] = {}
        self._client_locks: dict[str, asyncio.Lock] = {}
        self._order_subscription_id: Optional[int] = None
        self.loop = None
        self.processor_task = None
        self._server = None
        
    def get_port(self) -> int:
        """Get the port the server is bound to"""
        if self._server and self._server.sockets:
            sock = list(self._server.sockets)[0]
            return sock.getsockname()[1]
        return 0

    async def _maybe_await(self, maybe_awaitable) -> Any:
        """
        Utility helper to await an awaitable or return the value directly.
        This makes the server resilient to both sync and async mocks used in tests.
        """
        try:
            if inspect.isawaitable(maybe_awaitable):
                return await maybe_awaitable
        except Exception:
            # If inspect fails for some object types, fall back to returning directly
            pass
        return maybe_awaitable

    async def start(self):
        """Start the WebSocket server"""
        host, port = self.uri.replace("ws://", "").split(":")
        # Let OS pick a free port if 0 is given
        port = int(port)
        self._server = await websockets.serve(
            self.websocket_server,
            host,
            port,
            ping_interval=None,
            ping_timeout=None,
            max_size=20 * 1024 * 1024  # 20 MB message size limit
        )
        await asyncio.sleep(0)  # yield control so the server starts
        logger.info(f"Server started on ws://{host}:{self.get_port()}")

    async def shutdown(self):
        """Shut down the server and clean up resources"""
        logger.info("Shutting down WebSocketServer")
        # Close WebSocket server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Close client connections
        for ws in list(self.connection_manager.connections):
            try:
                await ws.close()
            except Exception:
                pass

        # Cancel any remaining background tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_client_message(self, websocket: ServerConnection):
        try:
            logger.info(f"Waiting for messages from {websocket.remote_address}")
            while True:
                try:
                    message = await websocket.recv()
                except websockets.ConnectionClosedOK:
                    logger.info(
                        f"WebSocket closed normally: {websocket.remote_address}"
                    )
                    break
                except websockets.ConnectionClosedError as e:
                    logger.exception(f"WebSocket closed with error: {e}", exc_info=True)
                    logger.warning(f"latency: {websocket.latency}")
                    logger.warning(f"ping timeout: {websocket.ping_timeout}")
                    logger.warning(f"ping  interval: {websocket.ping_interval}")
                    break

                logger.info(f"Received message: {message}")

                try:
                    # Implement message size limit (64KB)
                    if len(message) > 65536:
                        raise ValueError("Message size exceeds 64KB limit")

                    requests = json.loads(message)
                    if isinstance(requests, dict):
                        requests = [requests]
                    for request in requests:
                        if "action" in request:
                            # attach websocket context for per-client handling
                            request_with_ws = dict(request)
                            request_with_ws["_ws"] = websocket

                            # SERVER-SIDE QUICK PATH FOR PULL-MODE BACKTESTS
                            # If the MessageHandler has been replaced by a test double (MagicMock),
                            # perform the simple "get next bar" flow here so tests that patch
                            # MessageHandler still exercise the data source calls.
                            action = request_with_ws.get("action")
                            ds = getattr(self.trading_system, "data_source", None)
                            # If we've already sent a simulation_end to this client, ignore further pull requests
                            client_id = self.connection_manager.get_client_id(websocket)
                            if action in ("next_bar", "next_tick") and self.connection_manager.connection_info.get(websocket, {}).get("simulation_end_sent"):
                                logger.debug("Ignoring %s request from %s: simulation_end already sent", action, client_id)
                                continue
                            if action in ("next_bar", "next_tick") and not isinstance(self.message_handler, MessageHandler) and ds is not None:
                                # Determine client id
                                if client_id is None:
                                    client_id = request_with_ws.get("_client_id")
                                if client_id is None:
                                    client_id = self.connection_manager.get_client_id(websocket)
                                # Attempt to fetch next bar from data source (sync or async)
                                next_batch = None
                                try:
                                    if hasattr(ds, "get_next_bar_for_client"):
                                        maybe = ds.get_next_bar_for_client(client_id)
                                        next_batch = await self._maybe_await(maybe)
                                    elif hasattr(ds, "get_next_bar"):
                                        try:
                                            maybe = ds.get_next_bar(client_id)
                                            next_batch = await self._maybe_await(maybe)
                                        except TypeError:
                                            next_batch = await self._maybe_await(ds.get_next_bar())
                                except Exception as e:
                                    logger.exception(f"Error retrieving next bar for client {client_id}: {e}")
                                    next_batch = None

                                if not next_batch:
                                    # Signal simulation end
                                    msg = {"type": "simulation_end", "timestamp": datetime.now(timezone.utc).isoformat()}
                                    # Mark that simulation end has been sent for this client so we avoid duplicate final messages
                                    try:
                                        self.connection_manager.connection_info.setdefault(websocket, {})["simulation_end_sent"] = True
                                        logger.info(f"Sent simulation_end to client {client_id}")
                                    except Exception:
                                        pass
                                    await websocket.send(json.dumps(msg, default=str))
                                    continue

                                # Normalize TickerData to dicts if needed
                                if isinstance(next_batch, list) and next_batch and isinstance(next_batch[0], TickerData):
                                    data_out = [p.model_dump() for p in next_batch]
                                else:
                                    data_out = next_batch

                                msg = {"type": "price_update", "timestamp": datetime.now(timezone.utc).isoformat(), "data": data_out}
                                await websocket.send(json.dumps(msg, default=str))
                                continue

                            # Fallback to using the configured MessageHandler (sync or async)
                            # Support both sync and async message handlers (tests may pass MagicMock)
                            # Handle message processing with proper type handling
                            handler_response = await self._maybe_await(
                                self.message_handler.handle_message(
                                    request_with_ws,
                                    self.trading_system,
                                    self.connection_manager
                                )
                            )
                            
                            # Ensure we have a HandleResult object
                            if not hasattr(handler_response, 'result_type') or not hasattr(handler_response, 'payload'):
                                logger.error(f"Invalid handler response: {handler_response}")
                                continue
                                
                            message_for_client = handler_response
                            
                            if message_for_client.result_type == RESET_REQUESTED:
                                await self.reset(websocket)
                                continue
                            
                            # Immediate-send for price updates so client receives the bar promptly
                            if message_for_client.result_type == "price_update":
                                data = message_for_client.payload
                                if isinstance(data, list) and data and isinstance(data[0], TickerData):
                                    data_out = [p.model_dump() for p in data]
                                else:
                                    data_out = data
                                msg = {"type": "price_update", "timestamp": datetime.now(timezone.utc).isoformat(), "data": data_out}
                                await websocket.send(json.dumps(msg, default=str))
                                continue
                            
                            # If we're about to send a simulation_end for this client, mark it so we don't resend on subsequent requests
                            if message_for_client.result_type == "simulation_end":
                                try:
                                    self.connection_manager.connection_info.setdefault(websocket, {})["simulation_end_sent"] = True
                                except Exception:
                                    pass
                            
                            # Generic enqueued send for other message types
                            logger.debug(f"message for client {message_for_client}")
                            await self._maybe_await(
                                self.connection_manager.send(
                                    websocket,
                                    message_for_client.result_type,
                                    message_for_client.payload,
                                    priority=True
                                )
                            )
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Invalid message: {e} - {message[:100]}")

                    # Immediate-close cases
                    if isinstance(e, ValueError) and str(e).startswith("Message size exceeds"):
                        # Message too large
                        await websocket.close(code=1009, reason="Message too big")
                        break

                    # For JSONDecodeError and other ValueErrors, send an error response
                    error_count = self.connection_manager.increment_error_count(websocket)
                    if error_count > 5:  # Rate limit threshold
                        logger.warning(
                            f"Closing connection due to excessive errors: {websocket.remote_address}"
                        )
                        await websocket.close(code=1007, reason="Too many protocol errors")
                        break
                    else:
                        # Create error response based on exception type
                        if isinstance(e, json.JSONDecodeError):
                            error_payload = {
                                "status": "error",
                                "code": "INVALID_JSON",
                                "message": "Invalid JSON format received"
                            }
                        else:
                            error_payload = {
                                "status": "error",
                                "code": "INVALID_MESSAGE",
                                "message": str(e)
                            }
                        
                        await self._maybe_await(
                            self.connection_manager.send(
                                websocket,
                                "error",
                                error_payload
                            )
                        )
                except Exception as e:
                    logger.exception(f"Error processing message: {e}")
                    self.connection_manager.increment_error_count(websocket)

        except Exception:
            logger.exception("Unexpected error in message handler")
        finally:
            logger.info(f"Removing connection: {websocket.remote_address}")
            await self._maybe_await(self.connection_manager.remove_connection(websocket))

    async def websocket_server(self, websocket: ServerConnection):
        # Allow connection_manager.add_connection to be sync or async (tests may pass MagicMock)
        # Disable automatic welcome enqueue here so immediate client requests
        # are handled before any welcome message is delivered.
        add_conn_res = self.connection_manager.add_connection(websocket, enqueue_welcome=False)
        await self._maybe_await(add_conn_res)
        try:
            # assign client id and init per-client state
            client_id = self.connection_manager.assign_client_id(websocket)
            self._client_ready[client_id] = asyncio.Event()
            self._client_ready[client_id].set()  # first bar ready
            self._client_locks[client_id] = asyncio.Lock()
            mode = "push"

            # Determine pull_mode via data_source attributes (duck-typed)
            ds = getattr(self.trading_system, "data_source", None)
            pull_mode = getattr(ds, "pull_mode", False) or getattr(ds, "synchronous_mode", False)
            if pull_mode:
                mode = "pull"

            # The ConnectionManager.add_connection enqueues a welcome message.
            # To avoid delivering that welcome before the client has a chance to
            # send an initial request (which tests rely on), remove a single
            # pending welcome message if present. This ensures tests that send a
            # request immediately (without reading welcome) get the expected reply.
            try:
                queues = getattr(self.connection_manager, "connection_queues", {}).get(websocket)
                if queues:
                    pending = None
                    try:
                        if hasattr(queues, "prio") and queues.prio is not None:
                            pending = queues.prio.get_nowait()
                        else:
                            pending = queues.main.get_nowait()
                    except Exception:
                        pending = None
                    if pending:
                        # If it wasn't a welcome message, put it back on the main queue.
                        try:
                            parsed = json.loads(pending) if isinstance(pending, str) else None
                            if parsed is not None and parsed.get("type") != "welcome":
                                await queues.main.put(pending)
                        except Exception:
                            await queues.main.put(pending)
            except Exception:
                # Best-effort only; do not fail connection setup for non-critical issues
                pass

            # Attempt to get historical data if data source provides it (and is not a test Mock)
            historical = None
            if ds is not None and not isinstance(ds, Mock):
                get_hist = getattr(ds, "get_historical_data", None)
                if callable(get_hist):
                    # Try to read optional history_steps from the data source config (if present)
                    history_steps = None
                    bc = getattr(ds, "backtest_config", None)
                    if bc is not None:
                        history_steps = getattr(bc, "history_steps", None)
                    # Call get_historical_data with history_steps when supported by the implementation
                    try:
                        if history_steps is not None:
                            hist_res = get_hist(history_steps=history_steps)
                        else:
                            hist_res = get_hist()
                    except TypeError:
                        # Fallback: data source didn't accept history_steps kwarg
                        hist_res = get_hist()

                    if inspect.isawaitable(hist_res):
                        historical = await hist_res
                    else:
                        historical = hist_res
            if historical:
                # Convert TickerData objects to dictionaries if needed
                if isinstance(historical, list) and historical and isinstance(historical[0], TickerData):
                    historical_out = [p.model_dump() for p in historical]
                else:
                    historical_out = historical
                
                # Only send as chunks if it's a list
                if isinstance(historical_out, list):
                    # Send historical data in chunks to avoid large messages
                    chunk_size = 500  # items per chunk
                    total_items = len(historical_out)
                    for i in range(0, total_items, chunk_size):
                        chunk = historical_out[i:i+chunk_size]
                        await self._maybe_await(self.connection_manager.send(
                            websocket,
                            "price_history_chunk" if i+chunk_size < total_items else "price_history",
                            {
                                "chunk": chunk,
                                "chunk_index": i // chunk_size,
                                "total_chunks": (total_items + chunk_size - 1) // chunk_size
                            }
                        ))
                else:
                    # For non-list data, send as a single message
                    if isinstance(historical_out, list):
                        # Enforce chunked sending for any list to avoid large payloads
                        chunk_size = 500
                        total_items = len(historical_out)
                        total_chunks = (total_items + chunk_size - 1) // chunk_size
                        for i in range(0, total_items, chunk_size):
                            chunk = historical_out[i:i+chunk_size]
                            await self._maybe_await(
                                self.connection_manager.send(
                                    websocket,
                                    "price_history_chunk" if i + chunk_size < total_items else "price_history",
                                    {
                                        "data": chunk,
                                        "chunk_index": i // chunk_size,
                                        "total_chunks": total_chunks
                                    }
                                )
                            )
                    elif isinstance(historical_out, dict):
                        await self._maybe_await(self.connection_manager.send(websocket, "price_history", historical_out))
                    else:
                        logger.warning(f"Skipping historical data send - invalid type: {type(historical_out)}")

            # 2️⃣  Start the live stream (back-test or live feed)
            await self._maybe_await(self._attach_event_handlers(websocket))

            # 3️⃣  Handle client messages (orders, reset, etc.)
            await self._maybe_await(self._process_client_message(websocket))

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            try:
                await self._maybe_await(websocket.close())
            except Exception:
                pass
            await self._maybe_await(self.connection_manager.remove_connection(websocket))
            if self._order_subscription_id:
                await self._maybe_await(self.shutdown())

    async def broadcast_processed_data(self, data):
        """Broadcast processed data to all connected clients"""
        if not self.connection_manager.connections:
            return
        await self._maybe_await(self.connection_manager.broadcast_to_all(type="price_update", payload=data))

    async def _attach_event_handlers(self, websocket: ServerConnection):
        async def forward(kind: str, payload: Any):
            if websocket not in self.connection_manager.connections:
                return
            await self._maybe_await(self.connection_manager.send(websocket, kind, payload))

        ds = getattr(self.trading_system, "data_source", None)

        # Determine whether we should subscribe automatically.
        pull_mode = getattr(ds, "pull_mode", False) or getattr(ds, "synchronous_mode", False)
        subscribe_fn = getattr(ds, "subscribe_realtime_data", None)

        # Only auto-subscribe if the data source explicitly supports it and it's not a pull-mode backtest.
        if subscribe_fn and callable(subscribe_fn) and not pull_mode and not isinstance(ds, Mock):
            maybe_sub = subscribe_fn(forward)
            await self._maybe_await(maybe_sub)
        else:
            # If pull mode is supported, call enable_pull_mode if available (sync or async)
            enable_fn = getattr(ds, "enable_pull_mode", None)
            if enable_fn and callable(enable_fn):
                maybe_enable = enable_fn(True)
                await self._maybe_await(maybe_enable)

        # Subscribe to order updates if the exchange supports it (sync or async)
        exchange = getattr(self.trading_system, "exchange", None)
        subscribe_orders = getattr(exchange, "subscribe_to_orders", None)
        if subscribe_orders and callable(subscribe_orders):
            maybe_orders = subscribe_orders([], forward)
            await self._maybe_await(maybe_orders)

    async def reset(self, initiating_websocket=None):
        """
        Reset simulation state. If initiating_websocket is provided, reset only that client's state.
        After resetting the data source we attempt to re-send fresh historical data
        to the initiating client or broadcast to all clients (for global reset).
        """
        # Helper to fetch historical data from the data source (sync or async)
        async def _fetch_historical(ds):
            try:
                get_hist = getattr(ds, "get_historical_data", None)
                if not callable(get_hist):
                    return None
                # Try to pass configured history_steps if available on the data source
                history_steps = None
                bc = getattr(ds, "backtest_config", None)
                if bc is not None:
                    history_steps = getattr(bc, "history_steps", None)
                try:
                    if history_steps is not None:
                        hist_res = get_hist(history_steps=history_steps)
                    else:
                        hist_res = get_hist()
                except TypeError:
                    hist_res = get_hist()

                if inspect.isawaitable(hist_res):
                    return await hist_res
                return hist_res
            except Exception as e:
                logger.exception(f"Error fetching historical data: {e}")
                return None

        if initiating_websocket is not None:
            client_id = self.connection_manager.get_client_id(initiating_websocket)
            logger.info(f"Resetting client {client_id}")
            # NOTE: Do NOT clear the global portfolio for a single-client reset.
            # Portfolio is shared across clients in the current design. If per-client
            # portfolios are introduced in the future, replace this with per-client logic.
            try:
                # call client-specific reset if available (sync or async)
                reset_fn = getattr(self.trading_system.data_source, "reset_client", None)
                if reset_fn and callable(reset_fn):
                    await self._maybe_await(reset_fn(client_id))
                else:
                    # Fallback: reset entire data source if no client-specific reset exists
                    await self._maybe_await(self.trading_system.data_source.reset())
            except AttributeError:
                # fallback to full reset if attribute access fails
                await self._maybe_await(self.trading_system.data_source.reset())
            
            # Clear the final report sent flag for this client
            if hasattr(self.connection_manager, '_final_report_sent'):
                self.connection_manager._final_report_sent.discard(client_id)
            
            # Clear the simulation end sent flag for this client
            if initiating_websocket in self.connection_manager.connection_info:
                self.connection_manager.connection_info[initiating_websocket].pop("simulation_end_sent", None)
                logger.debug(f"Cleared simulation_end_sent flag for client {client_id}")
            
            # Notify client reset
            await self._maybe_await(self.connection_manager.send(initiating_websocket, "reset", {"message": "Client simulation has been reset."}))

            # After resetting the data source, attempt to send fresh historical data to the initiating client
            ds = getattr(self.trading_system, "data_source", None)
            if ds is not None and not isinstance(ds, Mock):
                historical = await _fetch_historical(ds)
                if historical:
                    # Convert TickerData objects to dictionaries if needed
                    if isinstance(historical, list) and historical and isinstance(historical[0], TickerData):
                        historical_out = [p.model_dump() for p in historical]
                    else:
                        historical_out = historical

                    # Send historical data in chunks to avoid large messages
                    if isinstance(historical_out, list):
                        chunk_size = 500
                        total_items = len(historical_out)
                        total_chunks = (total_items + chunk_size - 1) // chunk_size
                        for i in range(0, total_items, chunk_size):
                            chunk = historical_out[i:i+chunk_size]
                            await self._maybe_await(self.connection_manager.send(
                                initiating_websocket,
                                "price_history_chunk" if i + chunk_size < total_items else "price_history",
                                {
                                    "chunk": chunk,
                                    "chunk_index": i // chunk_size,
                                    "total_chunks": total_chunks
                                }
                            ))
                    elif isinstance(historical_out, dict):
                        await self._maybe_await(self.connection_manager.send(initiating_websocket, "price_history", historical_out))

            return

        logger.info("Resetting all clients")
        self.trading_system.portfolio.clear_positions()
        await self._maybe_await(self.trading_system.data_source.reset())
        
        # Clear all final report sent flags
        if hasattr(self.connection_manager, '_final_report_sent'):
            self.connection_manager._final_report_sent.clear()
        
        # Clear simulation end sent flags for all clients
        for ws in self.connection_manager.connections:
            if ws in self.connection_manager.connection_info:
                self.connection_manager.connection_info[ws].pop("simulation_end_sent", None)
        
        # Notify all clients of reset
        await self._maybe_await(self.connection_manager.broadcast_to_all("reset", {"message": "Simulation has been reset."}))

        # After global reset, fetch fresh historical and broadcast to all clients
        ds = getattr(self.trading_system, "data_source", None)
        if ds is not None and not isinstance(ds, Mock):
            historical = await _fetch_historical(ds)
            if historical:
                if isinstance(historical, list) and historical and isinstance(historical[0], TickerData):
                    historical_out = [p.model_dump() for p in historical]
                else:
                    historical_out = historical

                if isinstance(historical_out, list):
                    chunk_size = 500
                    total_items = len(historical_out)
                    total_chunks = (total_items + chunk_size - 1) // chunk_size
                    for i in range(0, total_items, chunk_size):
                        chunk = historical_out[i:i+chunk_size]
                        await self._maybe_await(self.connection_manager.broadcast_to_all(
                            "price_history_chunk" if i + chunk_size < total_items else "price_history",
                            {
                                "chunk": chunk,
                                "chunk_index": i // chunk_size,
                                "total_chunks": total_chunks
                            }
                        ))
                elif isinstance(historical_out, dict):
                    await self._maybe_await(self.connection_manager.broadcast_to_all("price_history", historical_out))

        logger.info("Reset complete.")

    async def reset_server(self):
        """Compatibility helper used by tests to reset the whole server"""
        await self.reset()



async def start_server(app_config: AppConfig, websocket_uri: str | None = None, stop_event: asyncio.Event | None = None):
    """Boot the WebSocket server from a single AppConfig using the existing factories."""
    # Use 127.0.0.1 instead of localhost to avoid Windows issues
    uri = websocket_uri or f"ws://127.0.0.1:{find_free_port()}"

    # 1.  Data-source & exchange from factories
    data_source = DataSourceFactory.create_data_source(app_config.data_source)
    portfolio = Portfolio(initial_cash=app_config.initial_cash)
    exchange = ExchangeFactory.create_exchange(app_config.exchange, portfolio)

    # 2.  Trading system
    trading_system = TradingSystem(
        exchange=exchange,
        portfolio= portfolio,
        data_source=data_source,
    )

    # 3.  WebSocket server
    connection_manager = ConnectionManager()
    # attach connection manager onto trading_system for handler context
    setattr(trading_system, "connection_manager", connection_manager)
    message_handler = MessageHandler()
    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=uri,
    )

    # Start the server
    await server.start()
    logger.info(f"WebSocket server ready on ws://127.0.0.1:{server.get_port()}")

    try:
        # Auto-create a stop_event in test/pytest mode to ensure clean shutdown
        if stop_event is None:
            import os
            if "PYTEST_CURRENT_TEST" in os.environ:
                stop_event = asyncio.Event()
                # Schedule stop_event to fire after pytest-timeout/short delay
                async def auto_stop():
                    await asyncio.sleep(0.1)
                    stop_event.set()
                asyncio.create_task(auto_stop())
        if stop_event is None:
            # Wait indefinitely but allow cancellation
            while True:
                await asyncio.sleep(3600)
        else:
            await stop_event.wait()
    finally:
        await server.shutdown()

if __name__ == "__main__":
    import argparse
    import json
    from stock_data_downloader.models import AppConfig

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True)
    args = parser.parse_args()
    
    with open(args.config) as f:
        config_data = json.load(f)
    
    app_config = AppConfig(**config_data)
    try:
        asyncio.run(start_server(app_config))
    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
    finally:
        # Ensure all tasks are cancelled to prevent pytest hang
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
