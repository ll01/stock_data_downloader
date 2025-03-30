import asyncio
import json
import unittest
from websockets import connect
from unittest.mock import MagicMock

import websockets

from stock_data_downloader.websocket_server.server import WebSocketServer


class TestWebSocketServerIntegration(unittest.IsolatedAsyncioTestCase):
    async def start_server(self):
        async with websockets.serve(
            self.server.websocket_server,
            "localhost",
            int(self.server_uri.split(":")[-1]),
            ping_interval=30,
            ping_timeout=40,
        ):
            await asyncio.Future()

    async def asyncSetUp(self):
        """
        Set up the server in a background thread before each test
        """
        self.server_uri = "ws://localhost:51549"
        self.simulated_prices = {
            "AAPL": [{"price": 150.0}],
            "GOOG": [{"price": 2800.0}],
        }
        self.server = WebSocketServer(
            uri=self.server_uri,
            simulated_prices=self.simulated_prices,
            realtime=False,
            start_prices={"AAPL": 150, "GOOG": 2800},
            interval=1.0,
            generated_prices_count=252 * 1,
        )

        # Start the server
        self.server_task = asyncio.create_task(self.start_server())
        # Give server time to start
        await asyncio.sleep(0.1)

    async def asyncTearDown(self):
        """
        Cleanup after the test is done.
        """
        self.server_task.cancel()
        try:
            await self.server_task
        except asyncio.CancelledError:
            pass

    async def test_message_handler_integration(self):
        """
        Integration test: Client sends a message to WebSocketServer, checks the response.
        """
        async with connect(self.server_uri) as websocket:
            message_to_send = {
                "action": "short",
                "ticker": "AAPL",
                "quantity": 10,
                "price": 150,
                "metadata": {"strategy": "pairs_trading", "type": "pair_leg"},
            }

            # Send a message to the WebSocket server
            await websocket.send(json.dumps(message_to_send))
            print(f"Sent message: {message_to_send}")

            # Wait for a response from the WebSocket server
            response = await websocket.recv()
            print(f"Received response: {response}")

            
            assert len(self.server.connections) == 1


            # Parse and validate the response
            response_data = json.loads(response)
            self.assertEqual(response_data.get("status"), "executed")
            self.assertEqual(response_data.get("action"), "SHORT")
            self.assertEqual(response_data.get("ticker"), "AAPL")
        assert len(self.server.connections) == 0
           
    async def test_invalid_message(self):
        """
        Integration test: Client sends an invalid message to WebSocketServer, checks the response.
        """
        async with connect(self.server_uri) as websocket:
            invalid_message = "invalid json data"
            await websocket.send(invalid_message)
            print(f"Sent invalid message: {invalid_message}")

            # Wait for a response from the WebSocket server
            response = await websocket.recv()
            print(f"Received response: {response}")

            # In a real scenario, the server might close the connection or send an error message
            self.assertIn("error", response)


if __name__ == "__main__":
    unittest.main()