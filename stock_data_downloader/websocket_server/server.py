import asyncio
import json
import logging
import socket
from typing import Any, Dict, List, Optional

import websockets
from websockets.asyncio.server import ServerConnection
# from websockets.asyncio.client import ServerConnection

from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
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
from stock_data_downloader.websocket_server.MessageHandler import RESET_REQUESTED, MessageHandler


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
                            request, self.exchange, self.simulation_running
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

    async def run_realtime(self):
        """Run the realtime price generator and broadcast to all clients."""

        async def on_price_update(price_batch: List[Dict[str, float]]):
            try:
                if not self.connection_manager.connections:
                    logger.info("No clients connected, pausing realtime updates")
                    return
                await self.connection_manager.broadcast_to_all(
                    type="price_update", payload=price_batch
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
            historical_data = await self.data_source.get_historical_data()

            if not historical_data:
                logger.warning("No historical data received from data source.")
                await self.connection_manager.send(
                    websocket,
                    "price_update",
                    {"data": [], "sub_action": "price_history"},
                )
                return

            any_ticker = next(iter(historical_data))
            total_timesteps = len(historical_data[any_ticker])
            batch_size = 100

            for i in range(0, total_timesteps, batch_size):
                timestep_batch: List[
                    List[Dict[str, Any]]
                ] = []  # List of timesteps, each timestep is a list of ticker data

                for step_index in range(i, min(i + batch_size, total_timesteps)):
                    current_timestep_data: List[Dict[str, Any]] = []
                    for ticker, data_list in historical_data.items():
                        if step_index < len(data_list):  # Safety check
                            ohlc_data = data_list[step_index]
                            current_timestep_data.append(
                                {"ticker": ticker, **ohlc_data}
                            )
                    timestep_batch.append(current_timestep_data)

                await self.connection_manager.send(
                    websocket,
                    "price_update",
                    {"data": timestep_batch, "sub_action": "price_history"},
                )
                await asyncio.sleep(0.01)  # Small delay between batches

            logger.info(
                f"Finished sending historical data to {websocket.remote_address}"
            )

        except Exception:
            logger.exception(
                f"Error sending historical data to {websocket.remote_address}"
            )
            # Optionally send an error message to the client
            await self._send_rejection(
                websocket,
                {"action": "get_historical_data"},
                reason="Failed to retrieve historical data",
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
        await self.connection_manager.broadcast_to_all(type="reset", payload=reset_message)

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
        elif not self.realtime and initiating_websocket:
            logging.info(
                f"Sending historical data to initiating client {initiating_websocket.remote_address} after reset."
            )
            await self.send_historical_data(initiating_websocket)



async def start_websocket_server(
    # These parameters are now used to configure the DataSource, not the server directly
    seed: Optional[int] = None,
    start_prices: Optional[Dict[str, float]] = None,
    stats: Optional[Dict[str, TickerStats]] = None,
    simulation_interval: float = 1.0,  # Renamed to avoid confusion with websocket interval
    wait_time: float = 1.0,  # Time between realtime updates
    generated_prices_count: int = 252 * 1,
    initial_cash: float = 100000.0,  # Add initial cash param
    websocket_uri: Optional[str] = None,
    realtime: bool = False,
    # Remove simulated_prices as it's an output/internal state of the data source
    # simulated_prices: Optional[Dict[str, List[Dict[str, float]]]] = None,
):
    """Start and run the WebSocket server."""
    if websocket_uri:
        uri = websocket_uri
        host = uri.split("://")[-1].split(":")[0]
        port = int(uri.split(":")[-1])
    else:
        port = find_free_port()
        host = "localhost"  # Or "0.0.0.0" for external access
        uri = f"ws://{host}:{port}"

    # --- Instantiate the Data Source ---
    # Create the specific data source implementation (BrownianMotionDataSource)
    # using the provided parameters.
    if stats is None or start_prices is None:
        logger.error("stats and start_prices must be provided to start the simulation.")
        # Handle error appropriately, maybe raise exception or return
        return

    # Note: If you had other data source types (e.g., LiveDataSource),
    # you would choose which one to instantiate here based on configuration.
    # For this example, we assume BrownianMotionDataSource is used.

    data_source: DataSourceInterface = BrownianMotionDataSource(
        stats=stats,
        start_prices=start_prices,
        timesteps=generated_prices_count,  # Use the count for timesteps
        interval=simulation_interval,  # Use the simulation interval
        seed=seed,
        wait_time=wait_time
        if realtime
        else 0.0,  # Use wait_time for realtime, maybe 0 or small for non-realtime historical delivery
    )

    # --- Instantiate the WebSocket Server ---
    # Pass the created data source instance to the server
    server = WebSocketServer(
        data_source=data_source,  # Pass the instance
        uri=uri,
        realtime=realtime,
        initial_cash=initial_cash,  # Pass initial cash
        # max_in_flight_messages defaults to 10, can be added as param if needed
    )

    logger.info(
        f"Starting WebSocket server on {uri} with {type(data_source).__name__} in {'realtime' if realtime else 'simulation'} mode"
    )

    # Start the websockets server
    async with websockets.serve(
        server.websocket_server,
        host,  # Use the parsed host
        port,  # Use the parsed port
        ping_interval=None,  # Keep ping handling simple for simulation
        ping_timeout=None,
    ):
        # The server will run until the loop is stopped.
        # Use asyncio.Future() to keep the server running indefinitely
        # until cancelled (e.g., by KeyboardInterrupt).
        await asyncio.Future()
