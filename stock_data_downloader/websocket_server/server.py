import asyncio
import json
import logging
import socket
from typing import Any, Dict, List, Optional, Union

import websockets
from websockets.asyncio.server import ServerConnection

from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface
)
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult
from stock_data_downloader.websocket_server.trading_system import TradingSystem
from stock_data_downloader.websocket_server.DataSource.BrownianMotionDataSource import (
    BrownianMotionDataSource,
)
from stock_data_downloader.websocket_server.ExchangeInterface.HyperliquidExchange import (
    HyperliquidExchange,
)
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import TestExchange
from stock_data_downloader.websocket_server.MessageHandler import (
    RESET_REQUESTED,
    MessageHandler,
)
from stock_data_downloader.websocket_server.portfolio import Portfolio


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s",
)


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
        self.message_handler = message_handler
        self.uri = uri

        self.realtime = realtime
        self.realtime_task = None
        self.simulation_running = False
        self._order_subscription_id: Optional[int] = None
        self.loop = None

    async def _process_client_message(self, websocket: ServerConnection):
        try:
            logger.info(f"Waiting for messages from {websocket.remote_address}")
            while True:
                try:
                    message = await websocket.recv()
                except websockets.ConnectionClosedOK:
                    logger.info(f"WebSocket closed normally: {websocket.remote_address}")
                    break
                except websockets.ConnectionClosedError as e:
                    logger.exception(f"WebSocket closed with error: {e}", exc_info=True)
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
                            message_for_client = await self.message_handler.handle_message(
                                request,
                                self.trading_system,
                                self.simulation_running,
                                self.realtime,
                            )
                            if message_for_client.result_type == RESET_REQUESTED:
                                await self.reset_simulation()

                            await self.connection_manager.send(
                                websocket,
                                message_for_client.result_type,
                                message_for_client.payload,
                            )
                except (json.JSONDecodeError, ValueError) as e:
                    # Increment error count using ConnectionManager
                    error_count = self.connection_manager.increment_error_count(websocket)
                    logger.error(f"Invalid message: {e} - {message[:100]}")
                    
                    if error_count > 5:  # Rate limit threshold
                        logger.warning(f"Closing connection due to excessive errors: {websocket.remote_address}")
                        await websocket.close(code=1007, reason="Too many protocol errors")
                        break
                    else:
                        error_type = "invalid_json" if isinstance(e, json.JSONDecodeError) else "invalid_message"
                        await self.connection_manager.send(
                            websocket,
                            "error",
                            {
                                "type": error_type,
                                "message": str(e),
                                "error_count": error_count,
                                "max_errors": 5
                            }
                        )
                except Exception as e:
                    logger.exception(f"Error processing message: {e}")
                    self.connection_manager.increment_error_count(websocket)
                
        except Exception:
            logger.exception("Unexpected error in message handler")
        finally:
            logger.info(f"Removing connection: {websocket.remote_address}")
            await self.connection_manager.remove_connection(websocket)

    async def websocket_server(self, websocket: ServerConnection):
        await self.connection_manager.add_connection(websocket)

        try:
            if not self.realtime:
                await self.send_historical_data(websocket)
                await self._process_client_message(websocket)
            else:
                if len(self.connection_manager.connections) == 1 and (
                    self.realtime_task is None or self.realtime_task.done()
                ):
                    await self.send_historical_data(websocket)
                    self.realtime_task = asyncio.create_task(self.run_realtime())
                await self._process_client_message(websocket)

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            try:
                await websocket.close()
            except Exception:
                pass
                
            await self.connection_manager.remove_connection(websocket)

            if (
                self.realtime
                and not self.connection_manager.connections
                and self.realtime_task
            ):
                self.realtime_task.cancel()
            if self._order_subscription_id:
                await self.stop()

    async def run_realtime(self):
        loop = asyncio.get_running_loop()

        def on_price_update(price_batch: Dict[str, Union[str, float]]):
            try:
                if not self.connection_manager.connections:
                    return
                asyncio.run_coroutine_threadsafe(
                    self.connection_manager.broadcast_to_all(
                        type="price_update",
                        payload=[price_batch]
                    ),
                    loop
                )
            except asyncio.CancelledError:
                logger.info("Realtime task was cancelled")
            except Exception as e:
                logger.error(f"Error in realtime price generator: {e}")

        await self.trading_system.data_source.subscribe_realtime_data(callback=on_price_update)

    async def send_historical_data(self, websocket: ServerConnection):
        logger.info(f"Sending historical data to {websocket.remote_address}")
        try:
            historical_data: Dict[
                str, List[Dict[str, float]]
            ] = await self.trading_system.data_source.get_historical_data()
            if self.realtime:
                batch_size = 100
                action = "price_history"
            else:
                batch_size = 1
                action = "price_update"
            for _, time_serise in historical_data.items():
                historical_data_batches = [
                    time_serise[i : i + batch_size]
                    for i in range(0, len(time_serise), batch_size)
                ]
                if websocket not in self.connection_manager.connections:
                    logger.warning(
                        f"WebSocket connection {websocket.remote_address} is no longer active. Skipping historical data send."
                    )
                    return
                for batch in historical_data_batches:
                    await self.connection_manager.send(
                        websocket,
                        action,
                        batch,
                    )
                await asyncio.sleep(0.01)

            logger.info(
                f"Finished sending historical data to {websocket.remote_address}"
            )

        except Exception:
            logger.exception(
                f"Error sending historical data to {websocket.remote_address}"
            )
            fail_payload = {
                "action": "get_historical_data",
                "reason": "Failed to retrieve historical data for ",
            }
            await self.connection_manager.send(
                websocket,
                type="no history found",
                payload=fail_payload,
            )

    async def reset_simulation(self, initiating_websocket=None):
        logger.info("Resetting simulation...")
        if not self.realtime:
            self.trading_system.portfolio.clear_positions()
        if isinstance(
            self.trading_system.data_source, BrownianMotionDataSource
        ):
            await self.trading_system.data_source.reset()
        else:
            logger.warning(
                f"Data source {type(self.trading_system.data_source).__name__} does not support reset."
            )

        if self.realtime and self.realtime_task:
            self.realtime_task.cancel()

        reset_message = {"message": "Simulation has been reset."}
        await self.connection_manager.broadcast_to_all(
            "reset", reset_message
        )

        if self.realtime:
            if self.connection_manager.connections:
                logger.info(
                    "Re-subscribing to data source for realtime feed after reset."
                )

                async def data_source_callback(msg_type: str, payload: Any):
                    if msg_type == "price_update":
                        await self.connection_manager.broadcast_to_all(
                            type="price_update", payload=payload
                        )
                    else:
                        logger.warning(
                            f"Received unhandled message type from data source after reset: {msg_type}"
                        )

                    await self.trading_system.data_source.subscribe_realtime_data(
                        callback=data_source_callback
                    )

                logging.info("Realtime feed re-subscribed.")
            else:
                logging.info(
                    "No clients connected, not re-subscribing to realtime feed after reset."
                )

    async def start(self):
        if self.realtime and not self._order_subscription_id:
            logger.info(
                "Server running in realtime mode. Subscribing to order updates."
            )

            def order_update_callback(update_type: str, update_data: Any):
                asyncio.create_task(
                    self.message_handler.process_order_update(
                        update_data, self.realtime, self.trading_system.portfolio
                    )
                )

            try:
                self._order_subscription_id = await self.trading_system.exchange.subscribe_to_orders(
                    order_ids=[], callback=order_update_callback
                )
                logger.info(
                    f"Subscribed to order updates with ID: {self._order_subscription_id}"
                )
            except Exception as e:
                logger.error(f"Failed to subscribe to order updates: {e}")

    async def shutdown(self):
        if self.realtime_task:
            self.realtime_task.cancel()
            try:
                await self.realtime_task
            except asyncio.CancelledError:
                pass
        await self.stop()

    async def stop(self):
        if self._order_subscription_id:
            await self.trading_system.exchange.unsubscribe_to_orders([str(self._order_subscription_id)])
            self._order_subscription_id = None


async def start_simulation_server(
    seed: Optional[int] = None,
    start_prices: Dict[str, float] | None = None,
    stats: Dict[str, TickerStats] | None = None,
    simulation_interval: float = 1.0,
    generated_prices_count: int = 252,
    initial_cash: float = 100000.0,
    websocket_uri: Optional[str] = None,
):
    if stats is None or start_prices is None:
        logger.error("stats and start_prices must be provided to start the simulation.")
        raise ValueError("stats and start_prices are required for simulation.")

    if websocket_uri:
        uri = websocket_uri
        try:
            parts = uri.split("://")
            if len(parts) < 2 or ":" not in parts[-1]:
                 raise ValueError("Invalid websocket URI format")
            host_port = parts[-1].split(":")
            host = host_port[0]
            port = int(host_port[1])
        except (ValueError, IndexError) as e:
             logger.error(f"Invalid websocket URI: {websocket_uri} - {e}")
             raise
    else:
        port = find_free_port()
        host = "localhost"
        uri = f"ws://{host}:{port}"

    logger.info(f"Starting Simulation WebSocket server on {uri}")
    data_source: DataSourceInterface = BrownianMotionDataSource(
        stats=stats,
        start_prices=start_prices,
        timesteps=generated_prices_count,
        interval=simulation_interval,
        seed=seed,
        wait_time=0.0,
    )
    portfolio = Portfolio(initial_cash=initial_cash)
    exchange: ExchangeInterface = TestExchange(portfolio=portfolio)
    trading_system = TradingSystem(
        exchange=exchange,
        portfolio=portfolio,
        data_source=data_source

    )
    connection_manager = ConnectionManager()
    message_handler = MessageHandler()
    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=uri,
        realtime=False,
    )

    await server.start()

    logger.info(f"Simulation server running on {uri}")

    async with websockets.serve(
        server.websocket_server,
        host,
        port,
        ping_interval=None,
        ping_timeout=None,
    ):
        logger.info("WebSocket server listener started. Press Ctrl+C to stop.")
        await asyncio.Future()

    logger.info("Simulation server stopped.")


async def start_live_server(
    config: Dict[str, Any],
    tickers: List[str],
    trading_system: TradingSystem,
    websocket_uri: Optional[str] = None,
   
    
):
    if not tickers:
        logger.error("At least one ticker must be provided for the live server.")
        raise ValueError("tickers list cannot be empty for the live server.")

    if websocket_uri:
        uri = websocket_uri
        try:
            parts = uri.split("://")
            if len(parts) < 2 or ":" not in parts[-1]:
                raise ValueError("Invalid websocket URI format")
            host_port = parts[-1].split(":")
            host = host_port[0]
            port = int(host_port[1])
        except (ValueError, IndexError) as e:
            logger.error(f"Invalid websocket URI: {websocket_uri} - {e}")
            raise
    else:
        port = find_free_port()
        host = "localhost"
        uri = f"ws://{host}:{port}"

    logger.info(f"Starting Live WebSocket server on {uri}")

   

    connection_manager = ConnectionManager()
    message_handler = MessageHandler()

    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=uri,
        realtime=True,
    )

    await server.start()

    logger.info(f"Live server running on {uri}")

    async with websockets.serve(
        server.websocket_server,
        host,
        port,
        ping_interval=20,
        ping_timeout=20,
    ):
        logger.info("WebSocket server listener started. Press Ctrl+C to stop.")
        await asyncio.Future()

    logger.info("Live server stopped.")
