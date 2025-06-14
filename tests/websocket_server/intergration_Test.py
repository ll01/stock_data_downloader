import asyncio
import json
from typing import Dict
import unittest
import websockets
from websockets.exceptions import ConnectionClosed

# Assuming your project structure allows these imports
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.DataSource.BrownianMotionDataSource import (
    BrownianMotionDataSource,
)
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import (
    TestExchange,
)
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.websocket_server.trading_system import TradingSystem


class TestWebSocketServerIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Integration tests for the WebSocketServer.
    """

    async def asyncSetUp(self):
        """Set up a WebSocket server on a random free port before each test."""
        stats = {"AAPL": TickerStats(mean=0.0001, sd=0.015)}
        start_prices = {"AAPL": 150.0}
        portfolio = Portfolio(initial_cash=100000.0)
        data_source = BrownianMotionDataSource(
            stats=stats, start_prices=start_prices, timesteps=50, seed=42 # Reduced timesteps for faster tests
        )
        exchange = TestExchange(portfolio=portfolio)
        trading_system = TradingSystem(
            data_source=data_source, exchange=exchange, portfolio=portfolio
        )
        
        self.ws_server_instance = WebSocketServer(
            trading_system=trading_system,
            connection_manager=ConnectionManager(),
            message_handler=MessageHandler(),
            uri="",
            realtime=False,
        )

        self.server = await websockets.serve(
            self.ws_server_instance.websocket_server, "127.0.0.1", 0
        )

        host, port = list(self.server.sockets)[0].getsockname()
        self.server_uri = f"ws://{host}:{port}"

    async def asyncTearDown(self):
        """Gracefully shut down the server after each test."""
        self.server.close()
        await self.server.wait_closed()

    async def test_successful_trade_message(self):
        """
        Tests sending a valid trade order and receiving a successful confirmation
        after processing any initial history messages.
        """
        async with websockets.connect(self.server_uri) as websocket:
            trade_message = {
                "action": "order",
                "payload": {
                    "ticker": "AAPL",
                    "quantity": 10,
                    "price": 150,
                    "order_type": "buy",
                },
            }
            await websocket.send(json.dumps(trade_message))

            order_confirmations: Dict  = {}
            try:
                # Use a timeout for the entire message-finding process
                async with asyncio.timeout(5.0):
                    # CORRECTED: This properly loops over all incoming messages
                    async for message_raw in websocket:
                        message_data = json.loads(message_raw)
                        # If it's the message we want, save it and exit the loop
                        if message_data.get("type") == "order_confirmation":
                            order_confirmations = message_data
                            break
                        # Otherwise, it's a 'price_history' message; the loop continues
            except TimeoutError:
                self.fail("Test timed out waiting for the order confirmation")

            # Perform assertions on the captured confirmation message
            self.assertIsNotNone(order_confirmations, "Did not receive order confirmation")
            
            
            confirmation_payload = order_confirmations["payload"][0]
            self.assertEqual(confirmation_payload["status"], "FILLED")
            self.assertEqual(confirmation_payload["symbol"], "AAPL")
            self.assertEqual(confirmation_payload["quantity"], 10)

    async def test_invalid_json_message_closes_connection(self):
        """
        Tests that the server closes the connection when it receives an invalid JSON message.
        """
        async with websockets.connect(self.server_uri) as websocket:
            invalid_message = "this is not valid json"
            await websocket.send(invalid_message)
            
            # The server should close the connection upon the error.
            # Awaiting recv() on a closed connection will raise an exception.
            with self.assertRaises(ConnectionClosed):
                await websocket.recv()


if __name__ == "__main__":
    unittest.main()