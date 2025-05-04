import asyncio
import json
import logging
import os
import sys
import socket
from typing import Any, Dict, List, Optional, Union

import websockets
from websockets.asyncio.server import ServerConnection
# from websockets.asyncio.client import ServerConnection

from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager

from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import (
    HyperliquidDataSource,
)
from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
    ExchangeInterface,
)
# from stock_data_downloader.websocket_server.portfolio import Portfolio

from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
    DataSourceInterface,
)

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
        s.bind(("127.0.0.1", 0))  # Bind to any available port
        return s.getsockname()[1]


class WebSocketServer:
    def __init__(
        self,
        data_source: DataSourceInterface,
        exchange: ExchangeInterface,
        connection_manager: ConnectionManager,
        message_handler: MessageHandler,
        uri: str,
        max_in_flight_messages: int = 10,
        realtime: bool = False,
    ):
        self.data_source = data_source
        self.exchange = exchange
        self.connection_manager = connection_manager
        self.message_handler = message_handler
        self.uri = uri

        self.realtime = realtime
        self.realtime_task = None  # Store task reference for cancellation
        self.simulation_running = False
        self._order_subscription_id: Optional[int] = None
        self.loop = asyncio.get_event_loop()

        self.portfolio = Portfolio()

    async def _process_client_message(self, websocket: ServerConnection):
        try:
            logger.info(f"Waiting for messages from {websocket.remote_address}")
            while True:
                message = await websocket.recv()
                logger.info(f"Received message: {message}")
                requests = json.loads(message)
                if isinstance(requests, dict):
                    requests = [requests]
                for request in requests:
                    if "action" in request:
                        message_for_client = await self.message_handler.handle_message(
                            request,
                            self.exchange,
                            self.portfolio,
                            self.simulation_running,
                            self.simulation_running,
                        )
                        if message_for_client.result_type == RESET_REQUESTED:
                            await self.reset_simulation()

                        await self.connection_manager.send(
                            websocket,
                            message_for_client.result_type,
                            message_for_client.payload,
                        )
                await asyncio.sleep(0)
        except websockets.ConnectionClosedOK:
            logger.info(f"WebSocket closed normally: {websocket.remote_address}")
        except websockets.ConnectionClosedError:
            logger.exception("WebSocket closed with error:")
        except Exception:
            logger.exception("Unexpected error in message handler")
        finally:
            logger.info(f"Removing connection: {websocket.remote_address}")
            await websocket.wait_closed()
            await self.connection_manager.remove_connection(websocket)

    async def websocket_server(self, websocket: ServerConnection):
        await self.connection_manager.add_connection(websocket)

        try:
            if not self.realtime:
                # In simulation mode, run both handlers
                await asyncio.gather(
                    self._process_client_message(websocket),
                    return_exceptions=True,
                )
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
            await self.connection_manager.remove_connection(websocket)

            if (
                self.realtime
                and not self.connection_manager.connections
                and self.realtime_task
            ):
                self.realtime_task.cancel()
            if self._order_subscription_id:
                await self.stop()
            # Needed because hyperliquid dosn't close its websocket connection correctly when it's done
            os._exit(0) if os.name == "nt" else sys.exit(0)

    async def run_realtime(self):
        """Run the realtime price generator and broadcast to all clients."""

        def on_price_update(price_batch: Dict[str, Union[str, float]]):
            try:
                if not self.connection_manager.connections:
                    # logger.info("No clients connected, pausing realtime updates")
                    return
                print(price_batch)
                asyncio.run_coroutine_threadsafe(
                self.connection_manager.broadcast_to_all(
                    type="price_update",
                    payload=[price_batch]
                ),
                self.loop
            )

            except asyncio.CancelledError:
                logger.info("Realtime task was cancelled")
            except Exception as e:
                logger.error(f"Error in realtime price generator: {e}")

        await self.data_source.subscribe_realtime_data(callback=on_price_update)

    async def send_historical_data(self, websocket: ServerConnection):
        """Fetch historical data from the data source and send to a single client."""
        logger.info(f"Sending historical data to {websocket.remote_address}")
        try:
            historical_data: Dict[
                str, List[Dict[str, float]]
            ] = await self.data_source.get_historical_data()

            for _, time_serise in historical_data.items():
                batch_size = 100
                historical_data_batches = [
                    time_serise[i : i + batch_size]
                    for i in range(0, len(time_serise), batch_size)
                ]
                for batch in historical_data_batches:
                    await self.connection_manager.send(
                        websocket,
                        "price_history",
                        batch,
                    )
                await asyncio.sleep(0.01)  # Small delay between batches

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
        """Resets the simulation to its initial state."""
        logger.info("Resetting simulation...")
        if not self.realtime:
            self.portfolio = Portfolio()
        if isinstance(
            self.data_source, BrownianMotionDataSource
        ):  # Or check for a SimulationDataSourceInterface if you create one
            await self.data_source.reset()
        else:
            logger.warning(
                f"Data source {type(self.data_source).__name__} does not support reset."
            )

        # Cancel any running realtime task
        if self.realtime and self.realtime_task:
            self.realtime_task.cancel()

        # Notify all clients that a reset occurred
        reset_message = {"message": "Simulation has been reset."}
        await self.connection_manager.broadcast_to_all(
            type="reset", payload=reset_message
        )

        # For realtime mode, restart the task
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

                    await self.data_source.subscribe_realtime_data(
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
                        update_data, self.realtime, self.portfolio
                    )
                )

            try:
                self._order_subscription_id = await self.exchange.subscribe_to_orders(
                    order_ids=[], callback=order_update_callback
                )
                logger.info(
                    f"Subscribed to order updates with ID: {self._order_subscription_id}"
                )
            except Exception as e:
                logger.error(f"Failed to subscribe to order updates: {e}")

    async def stop(self):
        await self.exchange.unsubscribe_to_orders([])


async def start_simulation_server(
    seed: Optional[int] = None,
    start_prices: Dict[str, float] | None = None,
    stats: Dict[str, TickerStats] | None = None,
    simulation_interval: float = 1.0,  # Time *step* duration in simulation (logical time)
    generated_prices_count: int = 252, # Number of simulation steps/days
    initial_cash: float = 100000.0,
    websocket_uri: Optional[str] = None,
    # No wait_time needed here, historical data is sent in batches
):
    """Start and run the WebSocket server in simulation mode."""

    if stats is None or start_prices is None:
        logger.error("stats and start_prices must be provided to start the simulation.")
        raise ValueError("stats and start_prices are required for simulation.")

    if websocket_uri:
        uri = websocket_uri
        try:
            # Parse host and port from URI
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
        host = "localhost"  # Or "0.0.0.0" for external access if needed
        uri = f"ws://{host}:{port}"

    logger.info(f"Starting Simulation WebSocket server on {uri}")

    # --- Instantiate Dependencies for Simulation ---
    portfolio = Portfolio(initial_cash=initial_cash) # Create portfolio
    data_source: DataSourceInterface = BrownianMotionDataSource(
        stats=stats,
        start_prices=start_prices,
        timesteps=generated_prices_count, # Use the count for total steps
        interval=simulation_interval, # Use the simulation interval for data generation logic (if applicable)
        seed=seed,
        wait_time=0.0, # Historical data is generated then sent, not streamed in real-time
    )
    exchange: ExchangeInterface = TestExchange(portfolio=portfolio) # Create simulation exchange
    connection_manager = ConnectionManager()
    message_handler = MessageHandler() # MessageHandler doesn't need special params for sim vs live

    # --- Instantiate and Start the WebSocket Server ---
    server = WebSocketServer(
        data_source=data_source,
        exchange=exchange,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=uri,
        realtime=False, # Explicitly set to False for simulation
    )

    await server.start() # Perform server startup logic (less relevant for sim start())

    logger.info(f"Simulation server running on {uri}")

    # Start the websockets server listener
    async with websockets.serve(
        server.websocket_server,
        host,
        port,
        ping_interval=None, # Keep ping handling simple for simulation
        ping_timeout=None,
    ):
        # The server will run until the loop is stopped.
        logger.info("WebSocket server listener started. Press Ctrl+C to stop.")
        await asyncio.Future() # Keep the server running indefinitely

    logger.info("Simulation server stopped.")


async def start_live_server(
    config: Dict[str, Any],  # Configuration for Hyperliquid connection
    tickers: List[str],  # Tickers to subscribe to for data
   

    websocket_uri: Optional[str] = None,
):
    """Start and run the WebSocket server in live trading mode using Hyperliquid."""

    if not tickers:
        logger.error("At least one ticker must be provided for the live server.")
        raise ValueError("tickers list cannot be empty for the live server.")

    if websocket_uri:
        uri = websocket_uri
        try:
            # Parse host and port from URI
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
        host = "localhost"  # Or "0.0.0.0" for external access if needed
        uri = f"ws://{host}:{port}"

    logger.info(f"Starting Live WebSocket server on {uri}")

    # --- Instantiate Dependencies for Live Trading ---
    # For live trading, the Portfolio might represent the live account balance/positions.
    # Its initial state could be fetched from the exchange or start at a nominal value.

    # Create Hyperliquid Exchange and Data Source instances

    # network = "mainnet"
    exchange: ExchangeInterface = HyperliquidExchange(config, "testnet")
    data_source: DataSourceInterface = HyperliquidDataSource(config, "mainnet", tickers)

    connection_manager = ConnectionManager()
    message_handler = (
        MessageHandler()
    )  # MessageHandler doesn't need special params for sim vs live

    # --- Instantiate and Start the WebSocket Server ---
    server = WebSocketServer(
        data_source=data_source,
        exchange=exchange,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=uri,
        realtime=True,  # Explicitly set to True for live
    )

    await (
        server.start()
    )  # Perform server startup logic (subscribes to orders in realtime mode)

    logger.info(f"Live server running on {uri}")

    # Start the websockets server listener
    # In live mode, keeping pings alive is more important
    async with websockets.serve(
        server.websocket_server,
        host,
        port,
        ping_interval=20,  # Send a ping every 20 seconds
        ping_timeout=20,  # Close connection if no pong received in 20 seconds
    ):
        # The server will run until the loop is stopped.
        logger.info("WebSocket server listener started. Press Ctrl+C to stop.")
        await asyncio.Future()  # Keep the server running indefinitely

    logger.info("Live server stopped.")
