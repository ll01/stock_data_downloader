import asyncio
from datetime import datetime, timedelta
import json
import logging
import random
import socket
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

import websockets
from websockets.asyncio.server import ServerConnection
# from websockets.asyncio.client import ServerConnection

from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import (
    simulate_ohlc,
    simulate_prices,
)
from stock_data_downloader.websocket_server.portfolio import Portfolio

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"
)


def find_free_port():
    """Finds a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))  # Bind to any available port
        return s.getsockname()[1]


class WebSocketServer:
    def __init__(
        self,
        uri: str,
        simulated_prices: Optional[Dict[str, List[Dict[str, float]]]] = None,
        realtime: bool = False,
        start_prices: Optional[Dict[str, float]] = None,
        stats: Optional[Dict[str, TickerStats]] = None,
        interval: float = 1.0,
        generated_prices_count: int = 252 * 1,  # 1 year of daily data
        max_in_flight_messages: int = 10
    ):
        self.uri = uri
        self.simulated_prices = simulated_prices
        self.realtime = realtime
        self.start_prices = start_prices or {}  # Store initial prices for resets
        self.current_prices = self.start_prices.copy()  # Active prices
        self.stats = stats  # Store stats for simulation
        self.interval = interval  # Store interval for updates
        self.generated_prices_count = generated_prices_count
        self.connections: Set[ServerConnection] = set()
        self.realtime_task = None  # Store task reference for cancellation
        self.simulation_running = False
        self.portfolio = Portfolio()
        self.message_queue = asyncio.Queue()  # Queue to manage in-flight messages
        self.max_in_flight_messages = max_in_flight_messages  # Max queue size

    async def add_connection(self, websocket: ServerConnection):
        self.connections.add(websocket)
        logger.info(f"New connection from {websocket.remote_address}")

    async def remove_connection(self, websocket: ServerConnection):
        if websocket in self.connections:
            await websocket.close()
            self.connections.remove(websocket)
            logger.info(f"Connection from {websocket.remote_address} closed")

    async def message_handler(self, websocket: ServerConnection):
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
                        await self.handle_message(websocket, request)
                await asyncio.sleep(0)
        except websockets.ConnectionClosedOK as e:
            logger.info(f"WebSocket closed normally: {websocket.remote_address}")
        except websockets.ConnectionClosedError as e:
            logger.warning(f"WebSocket closed with error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in message handler: {e}")
        finally:
            logger.info(f"Removing connection: {websocket.remote_address}")
            await websocket.wait_closed()
            await self.remove_connection(websocket)

    async def websocket_server(self, websocket: ServerConnection):
        await self.add_connection(websocket)

        try:
            if not self.realtime:
                # In simulation mode, run both handlers
                await asyncio.gather(
                    self.emit_price_ticks(websocket),
                    self.message_handler(websocket),
                    return_exceptions=True,
                )
            else:
                if len(self.connections) == 1 and (
                    self.realtime_task is None or self.realtime_task.done()
                ):
                    self.realtime_task = asyncio.create_task(self.run_realtime())
                await self.message_handler(websocket)

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            await self.remove_connection(websocket)

            if self.realtime and not self.connections and self.realtime_task:
                self.realtime_task.cancel()

    async def emit_price_ticks(self, websocket: ServerConnection):
            """Send pre-generated simulation data to a single client."""
            self.simulation_running = True

            if not self.simulated_prices:
                if not self.stats or not self.start_prices:
                    raise ValueError("Stats and start prices are required for simulation.")
                logger.info("Generating simulated prices...")

                self.simulated_prices = simulate_prices(
                    self.stats,
                    self.start_prices,
                    self.generated_prices_count,
                    self.interval,
                )

            max_length = max(len(prices) for prices in self.simulated_prices.values())
            now = datetime.now()

            for i in range(max_length):
                if websocket not in self.connections:
                    logger.info("Client disconnected, stopping simulation")
                    break

                batch_data = []
                current_time = now + timedelta(seconds=i)

                for ticker, prices in self.simulated_prices.items():
                    if i < len(prices):
                        price_data = prices[i].copy()
                        self.current_prices[ticker] = price_data["close"]
                        batch_data.append(
                            {
                                "timestamp": current_time.isoformat(),
                                "ticker": ticker,
                                **price_data,
                            }
                        )

                if batch_data:
                    try:
                        # Add batch data to the message queue
                        await self.message_queue.put(batch_data)

                        # If the number of messages in the queue is too high, slow down
                        while self.message_queue.qsize() > self.max_in_flight_messages:
                            logger.info(f"Too many messages in flight ({self.message_queue.qsize()}). Slowing down.")
                            await asyncio.sleep(30)  # Slow down emission to avoid overloading

                        # Send messages from the queue to the websocket
                        if not self.message_queue.empty():
                            message_to_send = await self.message_queue.get()
                            # message_to_send = json.dumps({
                            #     "action": "update",
                            #     "data": message_to_send
                            # })
                            await websocket.send(json.dumps(message_to_send))

                    except websockets.ConnectionClosedOK:
                        logger.info(f"WebSocket closed normally: {websocket.remote_address}")
                    except websockets.ConnectionClosedError as e:
                        logger.warning(f"WebSocket closed with error: {e}")
                    except Exception as e:
                        logger.error(f"Unexpected error in message handler: {e}")
                        break

                    # Introduce a slight delay between ticks (to simulate market data feeds)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                    await asyncio.sleep(0) 

            self.simulation_running = False

    async def generate_realtime_prices(self) -> AsyncGenerator[List[Dict], None]:
        """Generates realtime prices indefinitely."""
        if not self.stats:
            raise ValueError("Stats are required for realtime simulation.")
        while True:
            batch_data = []
            current_time = datetime.now().isoformat()

            for ticker, ticker_stats in self.stats.items():
                ohlc = simulate_ohlc(
                    ticker_stats.mean,
                    ticker_stats.sd,
                    self.current_prices[ticker],
                    self.interval,
                )
                self.current_prices[ticker] = ohlc["close"]

                batch_data.append({"timestamp": current_time, "ticker": ticker, **ohlc})

            yield batch_data
            # Wait for 1 minute between updates
            await asyncio.sleep(60)

    async def broadcast_to_all(self, data):
        """Send data to all connected clients."""
        if not self.connections:
            return

        message = json.dumps(data)
        disconnected = set()

        for websocket in self.connections:
            try:
                await websocket.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(websocket)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
                disconnected.add(websocket)

        # Remove disconnected clients
        for websocket in disconnected:
            self.connections.remove(websocket)

    async def run_realtime(self):
        """Run the realtime price generator and broadcast to all clients."""
        try:
            if not self.stats:
                raise ValueError("Stats are required for realtime simulation.")

            logger.info("Starting realtime price updates...")
            async for price_batch in self.generate_realtime_prices():
                if not self.connections:
                    logger.info("No clients connected, pausing realtime updates")
                    break
                await self.broadcast_to_all(price_batch)
        except asyncio.CancelledError:
            logger.info("Realtime task was cancelled")
        except Exception as e:
            logger.error(f"Error in realtime price generator: {e}")

    async def _send_rejection(
        self, websocket: ServerConnection, data: Dict, reason: str
    ):
        """Standard rejection format"""
        await websocket.send(
            json.dumps(
                {
                    "status": "rejected",
                    "order": data,
                    "reason": reason,
                    "valid_actions": ["buy", "sell", "reset"],
                    "valid_tickers": list(self.current_prices.keys()),
                }
            )
        )

    async def handle_message(self, websocket: ServerConnection, data: Dict[str, Any]):
        action = data.get("action")
        ticker = data.get("ticker", "")
        quantity = data.get("quantity", 0)
        price = data.get("price", 0)

        if action == "reset":
            await self.reset_simulation(websocket)
            await websocket.send(
                json.dumps(
                    {
                        "status": "reset",
                        "portfolio": json.dumps(vars(self.portfolio)),
                    }
                )
            )
            return

        # Input validation
        if not ticker:
            await self._send_rejection(websocket, data, reason="Missing ticker")
            return

        if quantity <= 0:
            await self._send_rejection(
                websocket, data, reason=f"Invalid quantity: {quantity}"
            )
            return

        if price <= 0:
            await self._send_rejection(
                websocket, data, reason=f"Invalid price: {quantity}"
            )
            return

        if ticker not in self.current_prices:
            await self._send_rejection(
                websocket, data, reason=f"Unknown ticker: {ticker}"
            )
            return

        try:
            if action == "buy":
                self.portfolio.buy(ticker, quantity, price)
                await self._send_execution(websocket, data, price, "BUY")

            elif action == "sell":
                self.portfolio.sell(ticker, quantity, price)
                await self._send_execution(websocket, data, price, "SELL")

            elif action == "short":
                self.portfolio.short(ticker, quantity, price)
                await self._send_execution(websocket, data, price, "SHORT")

            elif action == "cover":  # New action to close short positions
                self.portfolio.sell(
                    ticker, quantity, price
                )  # Uses same sell logic for covering
                await self._send_execution(websocket, data, price, "COVER")

            else:
                await self._send_rejection(
                    websocket, data, reason=f"Unknown action: {action}"
                )

        except Exception as e:
            logger.error(f"Trade execution failed: {str(e)}")
            await self._send_rejection(websocket, data, reason=str(e))

    async def _send_execution(self, websocket, data, price, action_type):
        """Send standardized execution confirmation"""
        await websocket.send(
            json.dumps(
                {
                    "status": "executed",
                    "action": action_type,
                    "ticker": data["ticker"],
                    "quantity": data["quantity"],
                    "price": price,
                    "portfolio": vars(self.portfolio),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        )

    async def reset_simulation(self, initiating_websocket=None):
        """Resets the simulation to its initial state."""
        logger.info("Resetting simulation...")

        # Reset current prices to the provided start prices
        self.current_prices = self.start_prices.copy()

        self.portfolio = Portfolio()

        # Cancel any running realtime task
        if self.realtime and self.realtime_task:
            self.realtime_task.cancel()

        # Notify all clients that a reset occurred
        reset_message = {"type": "reset", "message": "Simulation has been reset."}
        await self.broadcast_to_all(reset_message)

        # For realtime mode, restart the task
        if self.realtime and self.connections:
            self.realtime_task = asyncio.create_task(self.run_realtime())
        # For simulation mode, restart emission for the client that requested reset
        elif not self.realtime and initiating_websocket:
            self.simulation_running = False  # Fce reset of the simulation flag
            await self.emit_price_ticks(initiating_websocket)


async def start_websocket_server(
    simulated_prices: Optional[Dict[str, List[Dict[str, float]]]] = None,
    start_prices: Optional[Dict[str, float]] = None,
    stats: Optional[Dict[str, TickerStats]] = None,
    interval: float = 1.0,
    websocket_uri: Optional[str] = None,
    realtime: bool = False,
    generated_prices_count: int = 252 * 1,
):
    """Start and run the WebSocket server."""
    if websocket_uri:
        uri = websocket_uri
    else:
        port = find_free_port()
        uri = f"ws://localhost:{port}"

    logger.info(
        f"Starting WebSocket server on {uri} in {'realtime' if realtime else 'simulation'} mode"
    )

    server = WebSocketServer(
        uri=uri,
        simulated_prices=simulated_prices,
        realtime=realtime,
        start_prices=start_prices,
        stats=stats,
        interval=interval,
        generated_prices_count=generated_prices_count,
    )

    async with websockets.serve(
        server.websocket_server,
        "localhost",
        int(uri.split(":")[-1]),
        ping_interval=None,
        ping_timeout=None,
        
    ):
        # For realtime mode, we just keep the server running
        # The realtime task will be started when clients connect
        await asyncio.Future()  # Run forever


# Example usage
# if __name__ == "__main__":
#     logging.basicConfig(level=logging.INFO)

#     # Example stats and start prices
#     example_stats = {
#         "AAPL": TickerStats(mean=0.0001, sd=0.015),
#         "MSFT": TickerStats(mean=0.0002, sd=0.012),
#     }

#     example_start_prices = {
#         "AAPL": 150.0,
#         "MSFT": 250.0,
#     }

#     # Choose mode: realtime=True for continuous updates, False for simulation
#     import sys
#     realtime_mode = len(sys.argv) > 1 and sys.argv[1].lower() == "realtime"

#     asyncio.run(
#         start_websocket_server(
#             start_prices=example_start_prices,
#             stats=example_stats,
#             realtime=realtime_mode,
#         )
#     )
