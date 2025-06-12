import asyncio
import json
import unittest
import websockets
from websockets.exceptions import ConnectionClosedError

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


class TestWebSocketServerIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Integration tests for the WebSocketServer.

    These tests start a server instance in the background of the same event loop
    and connect to it as a client to verify end-to-end functionality without deadlocks.
    """

    async def asyncSetUp(self):
        """
        Set up a WebSocket server instance on a random free port before each test.
        """
        # 1. Define mock data and dependencies for the simulation
        stats = {
            "AAPL": TickerStats(mean=0.0001, sd=0.015),
            "GOOG": TickerStats(mean=0.0002, sd=0.02),
        }
        start_prices = {"AAPL": 150.0, "GOOG": 2800.0}
        portfolio = Portfolio(initial_cash=100000.0)
        data_source = BrownianMotionDataSource(
            stats=stats, start_prices=start_prices, timesteps=252, seed=42
        )
        exchange = TestExchange(portfolio=portfolio)

        # 2. Instantiate the WebSocketServer with its components
        self.ws_server_instance = WebSocketServer(
            data_source=data_source,
            exchange=exchange,
            connection_manager=ConnectionManager(),
            message_handler=MessageHandler(),
            uri="",  # The URI will be determined by websockets.serve
            realtime=False,
        )

        # 3. Start the server on a random available port (port=0) forcing IPv4
        self.server = await websockets.serve(
            self.ws_server_instance.websocket_server,
            "127.0.0.1",  # Force IPv4 binding
            0,
        )

        # 4. Get the actual URI (IPv4 format is simple)
        host, port = list(self.server.sockets)[0].getsockname()
        self.server_uri = f"ws://{host}:{port}"
        print(f"Test server started on {self.server_uri}")

    async def asyncTearDown(self):
        """
        Gracefully shut down the server after each test.
        """
        print(f"Closing test server on {self.server_uri}")
        self.server.close()
        await self.server.wait_closed()
        print("Test server closed.")

    async def test_successful_trade_message(self):
        """
        Tests sending a valid trade order and receiving a successful 'executed' confirmation.
        """
        async with websockets.connect(self.server_uri) as websocket:
            trade_message = {
                "action": "short",
                "ticker": "AAPL",
                "quantity": 10,
                "price": 150,
                "metadata": {"strategy": "pairs_trading"},
            }

            await websocket.send(json.dumps(trade_message))
            response_raw = await websocket.recv()
            print(f"Received response: {response_raw}")

            # Parse and validate the confirmation
            response_data = json.loads(response_raw)
            self.assertEqual(response_data.get("status"), "executed")
            self.assertEqual(
                response_data.get("action"), "SHORT"
            )  # Server uppercases the action
            self.assertEqual(response_data.get("ticker"), "AAPL")
            self.assertEqual(response_data.get("payload", {}).get("quantity"), 10)

    # async def test_invalid_json_message_closes_connection(self):
    #     """
    #     Tests that the server closes the connection when it receives an invalid JSON message.
    #     """
    #     async with websockets.connect(self.server_uri) as websocket:
    #         invalid_message = "this is not valid json"
    #         await websocket.send(invalid_message)

    #         # Your server's exception handler closes the connection upon a JSON decode error
    #         # without sending a final message. Therefore, recv() should raise a ConnectionClosedError.
    #         with self.assertRaises(ConnectionClosedError):
    #             await websocket.recv()
    #         print("Verified that connection was correctly closed by the server.")


if __name__ == "__main__":
    unittest.main()
