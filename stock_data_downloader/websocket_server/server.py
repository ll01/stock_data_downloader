import asyncio
from datetime import datetime, timedelta
import json
import logging
import random
import socket
from typing import AsyncGenerator, Dict, List, Optional, Set

import websockets
from websockets.asyncio.client import ClientConnection
from websockets import broadcast

from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import simulate_ohlc

logger = logging.getLogger(__name__)


def find_free_port():
    """Finds a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))  # Bind to any available port
        return s.getsockname()[1]


class WebSocketServer:
    connections: Set[ClientConnection] = set()

    def __init__(
        self,
        uri: str,
        simulated_prices: Dict[str, List[Dict[str, float]]],
        realtime: bool = False,
    ):
        self.uri = uri
        self.simulated_prices = simulated_prices
        self.realtime = realtime

    async def add_connection(self, websocket: ClientConnection):
        self.connections.add(websocket)
        logger.info(f"New connection from {websocket.remote_address}")

    async def remove_connection(self, websocket: ClientConnection):
        self.connections.remove(websocket)
        logger.info(f"Connection from {websocket.remote_address} closed")

    async def websocket_server(self, websocket):
        await self.add_connection(websocket)
        if not self.realtime:
            await self.emit_price_ticks(websocket)
        try:
            await websocket.wait_closed()
        finally:
            await self.remove_connection(websocket)

    async def emit_price_ticks(self, websocket):
        max_length = max(len(prices) for prices in self.simulated_prices.values())
        now = datetime.now()

        for i in range(max_length):
            batch_data = []
            current_time = now + timedelta(seconds=i)

            for ticker, prices in self.simulated_prices.items():
                if i < len(prices):
                    batch_data.append(
                        {
                            "timestamp": current_time.isoformat(),
                            "ticker": ticker,
                            **prices[i],
                        }
                    )

            if batch_data:
                try:
                    await websocket.send(json.dumps(batch_data))
                except websockets.exceptions.ConnectionClosedOK:
                    logger.info("Client disconnected gracefully.")
                    return  # Exit the loop if the client disconnects
                except Exception as e:
                    logger.error(f"Error sending data to WebSocket: {e}")
                    return  # Exit the loop on other errors

            # Introduce a slight random delay between ticks (optional, to simulate staggered updates)
            await asyncio.sleep(random.uniform(0, 0.3))

    async def generate_realtime_prices(
        self,
        stats: Dict[str, TickerStats],
        start_prices: Dict[str, float],
        interval: float = 1.0,
    ) -> AsyncGenerator[Dict[str, Dict[str, float]], None]:
        """Generates realtime prices indefinitely."""
        current_prices = start_prices.copy()
        while True:
            new_prices = {}
            for ticker, ticker_stats in stats.items():
                ohlc = simulate_ohlc(
                    ticker_stats.mean, ticker_stats.sd, current_prices[ticker], interval
                )
                new_prices[ticker] = ohlc
                current_prices[ticker] = ohlc["close"]
            yield new_prices
            await asyncio.sleep(1 * 60)

    async def run(self, stats, start_prices, interval):
        try:
            if self.realtime:
                async for new_prices in self.generate_realtime_prices(
                    stats, start_prices, interval
                ):
                    json_data = json.dumps(new_prices)
                    broadcast(self.connections, json_data)
        except Exception as e:
            logger.error(f"Error in WebSocket server: {e}")


async def handle_websocket_output(
    simulated_prices: Dict[str, List[Dict[str, float]]],
    start_prices: Dict[str, float],
    stats: Dict[str, TickerStats],
    interval: float,
    websocket_uri: Optional[str],
    realtime: bool = False,
):
    """Handles sending simulated prices to a WebSocket."""
    if websocket_uri:
        uri = websocket_uri
    else:
        port = find_free_port()
        uri = f"ws://localhost:{port}"
        logging.info(f"Starting WebSocket server on {uri}")
        server = WebSocketServer(uri, simulated_prices, realtime)

        async with websockets.serve(server.websocket_server, "localhost", port):
            await server.run(start_prices, stats, interval)
            await asyncio.Future()  # run forever
