import asyncio
import json
import logging
import socket
from typing import Any,  Optional

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
        self.simulation_running = False
        self._order_subscription_id: Optional[int] = None
        self.loop = None
        self.processor_task = None

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
                            message_for_client = (
                                await self.message_handler.handle_message(
                                    request,
                                    self.trading_system,
                                )
                            )
                            if message_for_client.result_type == RESET_REQUESTED:
                                await self.reset()

                            # Convert payload to TickerData objects if it's a list of dicts
                           
                                
                            await self.connection_manager.send(
                                websocket,
                                message_for_client.result_type,
                                message_for_client.payload ,
                                priority=True
                            )
                except (json.JSONDecodeError, ValueError) as e:
                    # Increment error count using ConnectionManager
                    error_count = self.connection_manager.increment_error_count(
                        websocket
                    )
                    logger.error(f"Invalid message: {e} - {message[:100]}")

                    if error_count > 5:  # Rate limit threshold
                        logger.warning(
                            f"Closing connection due to excessive errors: {websocket.remote_address}"
                        )
                        await websocket.close(
                            code=1007, reason="Too many protocol errors"
                        )
                        break
                    else:
                        error_type = (
                            "invalid_json"
                            if isinstance(e, json.JSONDecodeError)
                            else "invalid_message"
                        )
                        await self.connection_manager.send(
                            websocket,
                            "error",
                            {
                                "type": error_type,
                                "message": str(e),
                                "error_count": error_count,
                                "max_errors": 5,
                            },
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
            historical = await self.trading_system.data_source.get_historical_data()
            if historical:
                await self.connection_manager.send(
                    websocket, "price_history", historical
                )

            # 2️⃣  Start the live stream (back-test or live feed)
            await self._attach_event_handlers(websocket)

            # 3️⃣  Handle client messages (orders, reset, etc.)
            await self._process_client_message(websocket)

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            try:
                await websocket.close()
            except Exception:
                pass
            await self.connection_manager.remove_connection(websocket)
            if self._order_subscription_id:
                await self.shutdown()

    async def broadcast_processed_data(self, data):
        """Broadcast processed data to all connected clients"""
        if not self.connection_manager.connections:
            return
        await self.connection_manager.broadcast_to_all(
            type="price_update", payload=data
        )

  

    async def start(self):
        logger.info("Server running Subscribing to updates.")


    async def _attach_event_handlers(self, websocket: ServerConnection):
        async def forward(kind: str, payload: Any):
            if websocket not in self.connection_manager.connections:
                return
            await self.connection_manager.send(websocket, kind, payload)

        await self.trading_system.data_source.subscribe_realtime_data(forward)
        await self.trading_system.exchange.subscribe_to_orders([], forward)

    async def shutdown(self):
        if self._order_subscription_id:
            await self.trading_system.exchange.unsubscribe_to_orders(
                [str(self._order_subscription_id)]
            )
            self._order_subscription_id = None
    
    async def reset(self, initiating_websocket=None):
        """
        Reset the entire simulation.
        - Clears positions (always safe).
        - Calls `reset()` on the data-source if it supports it.
        - Broadcasts reset confirmation.
        """
        logger.info("Resetting ")

    
        self.trading_system.portfolio.clear_positions()


        await self.trading_system.data_source.reset()
        

        # 3. Notify all clients
        await self.connection_manager.broadcast_to_all(
            "reset", {"message": "Simulation has been reset."}
        )

        logger.info("Reset complete.")



async def start_server(app_config: AppConfig, websocket_uri: str | None = None):
    """Boot the WebSocket server from a single AppConfig using the existing factories."""
    uri = websocket_uri or f"ws://localhost:{find_free_port()}"

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
    message_handler = MessageHandler()
    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=uri,
    )

    # 4.  Listener
    host, port = uri.replace("ws://", "").split(":")
    await server.start()  # subscribe to orders, etc.

    async with websockets.serve(
        server.websocket_server,
        host,
        int(port),
        ping_interval=None,
        ping_timeout=None,
    ):
        logger.info(f"WebSocket server ready on {uri}")
        await asyncio.Future()
