# import asyncio
# import json
# import unittest
# from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
# import websockets
# from websockets.exceptions import ConnectionClosedOK
# from unittest.mock import AsyncMock, MagicMock, patch

# from stock_data_downloader.data_processing.TickerStats import TickerStats
# from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager

# from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import (
#     DataSourceInterface,
# )
# from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import (
#     ExchangeInterface,
# )
# from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import (
#     TestExchange,
# )
# from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
# from stock_data_downloader.websocket_server.portfolio import Portfolio
# from stock_data_downloader.websocket_server.server import WebSocketServer
# from stock_data_downloader.websocket_server.trading_system import TradingSystem


# class TestWebSocketServerUnit(unittest.IsolatedAsyncioTestCase):
#     async def asyncSetUp(self):
#         """Create a test server instance on a random free port"""
#         portfolio = Portfolio(initial_cash=100000)
#         exchange: ExchangeInterface = TestExchange(portfolio=portfolio)

#         # Create data source
#         data_source: DataSourceInterface = BacktestDataSource(
#             stats={"AAPL": TickerStats(mean=0.0001, sd=0.015)},
#             start_prices={"AAPL": 100},
#         )

#         # Create TradingSystem instance
#         trading_system = TradingSystem(
#             exchange=exchange, portfolio=portfolio, data_source=data_source
#         )

#         connection_manager = ConnectionManager()
#         message_handler = MessageHandler()

#         # Initialize WebSocketServer with new parameters
#         self.server_instance = WebSocketServer(
#             trading_system=trading_system,
#             connection_manager=connection_manager,
#             message_handler=message_handler,
#             uri="",  # URI determined by websockets.serve
#             realtime=False,
#         )

#         # Start server on random available port (port=0)
#         self.server = await websockets.serve(
#             self.server_instance.websocket_server,
#             "127.0.0.1",  # Force IPv4 binding
#             0,
#         )

#         # Get actual server URI
#         host, port = list(self.server.sockets)[0].getsockname()
#         self.server_uri = f"ws://{host}:{port}"

#     async def asyncTearDown(self):
#         """Gracefully shut down server after each test"""
#         self.server.close()
#         await self.server.wait_closed()

#     async def test_connection_management(self):
#         """Test adding and removing connections"""
#         mock_ws = AsyncMock()

#         # Test adding connection
#         await self.server_instance.connection_manager.add_connection(mock_ws)
#         assert mock_ws in self.server_instance.connection_manager.connections

#         # Test removing connection
#         await self.server_instance.connection_manager.remove_connection(mock_ws)
#         assert mock_ws not in self.server_instance.connection_manager.connections

#     async def test_message_handling(self):
#         """Test handling different message types"""

#         # Test buy order
#         buy_msg = {
#             "action": "order",
#             "data": {
#                 "ticker": "AAPL",
#                 "quantity": 10,
#                 "price": 155.0,
#                 "order_type": "buy",
#             },
#         }
#         response = await self.server_instance.message_handler.handle_message(
#             buy_msg,
#             self.server_instance.trading_system,
#             self.server_instance.simulation_running,
#             self.server_instance.realtime,
#         )
#         # Verify order response
#         assert response.result_type == "order_confirmation"

#     async def test_simulation_mode(self):
#         """Test simulation mode: client connects, sends an order, and receives confirmation."""
#         mock_ws_client = AsyncMock()
#         mock_ws_client.remote_address = ("127.0.0.1", 12345)

#         # Simulate the client sending one order message and then closing the connection.
#         buy_order_message = json.dumps(
#             {
#                 "action": "order",
#                 "data": {
#                     "ticker": "AAPL",
#                     "quantity": 5,
#                     "price": 100.5,
#                     "order_type": "buy",
#                 },
#             }
#         )
#         mock_ws_client.recv.side_effect = [
#             buy_order_message,
#             ConnectionClosedOK(None, None),
#         ]

#         # Mock the data source to avoid actual data generation
#         with patch.object(
#             self.server_instance.trading_system.data_source,
#             "get_historical_data",
#             return_value={"AAPL": []},  # Return empty data for simplicity
#         ) as mock_get_historical:

#             # Run the server's main handler with the mocked client
#             await self.server_instance.websocket_server(mock_ws_client)

#             # Assert that historical data was requested
#             await asyncio.sleep(0)
#             mock_get_historical.assert_awaited_once()

#             # Check that an order confirmation was sent to the client
#             sent_messages = [
#                 json.loads(call.args[0]) for call in mock_ws_client.send.call_args_list
#             ]
#             order_confirmations = [
#                 msg for msg in sent_messages if msg.get("type") == "order_confirmation"
#             ]
          
#             self.assertEqual(len(order_confirmations), 1)
#             confirmation_payload = order_confirmations[0]["data"][0]
#             self.assertEqual(confirmation_payload["status"], "FILLED")
#             self.assertEqual(confirmation_payload["symbol"], "AAPL")
#             self.assertEqual(confirmation_payload["quantity"], 5)

#             # Verify the final state of the portfolio
#             self.assertIn("AAPL", self.server_instance.trading_system.portfolio.positions)
#             self.assertEqual(
#                 self.server_instance.trading_system.portfolio.positions["AAPL"][0], 5
#             )

#             # Ensure the connection was closed and removed
#             mock_ws_client.close.assert_awaited_once()
#             self.assertNotIn(
#                 mock_ws_client, self.server_instance.connection_manager.connections
#             )

#     async def test_broadcast(self):
#         """Test broadcasting to multiple clients"""
#         mock_ws1 = AsyncMock()
#         mock_ws2 = AsyncMock()

#         # Add connections
#         await self.server_instance.connection_manager.add_connection(mock_ws1)
#         await self.server_instance.connection_manager.add_connection(mock_ws2)

#         # Test broadcast
#         test_data = {"test": "data"}
#         await self.server_instance.connection_manager.broadcast_to_all(
#             "test_event", test_data
#         )

#         # Verify both clients received data
#         expected_call = json.dumps({"type": "test_event", "data": test_data})
#         mock_ws1.send.assert_awaited_once_with(expected_call)
#         mock_ws2.send.assert_awaited_once_with(expected_call)

#     async def test_multiple_connections(self):
#         """Test handling multiple concurrent connections"""
#         mock_ws1 = AsyncMock()
#         mock_ws2 = AsyncMock()

#         await self.server_instance.connection_manager.add_connection(mock_ws1)
#         await self.server_instance.connection_manager.add_connection(mock_ws2)

#         assert len(self.server_instance.connection_manager.connections) == 2
#         await self.server_instance.connection_manager.remove_connection(mock_ws1)
#         assert len(self.server_instance.connection_manager.connections) == 1

#     async def test_order_execution(self):
#         """Test order execution flow"""
#         self.server_instance.current_prices = {"AAPL": 150.0}  # type: ignore[attr-defined]

#         orders = [
#             {
#                 "action": "order",
#                 "data": {
#                     "ticker": "AAPL",
#                     "quantity": 10,
#                     "price": 150.0,
#                     "order_type": "buy",
#                 },
#             },
#             {
#                 "action": "order",
#                 "data": {
#                     "ticker": "AAPL",
#                     "quantity": 5,
#                     "price": 150.0,
#                     "order_type": "sell",
#                 },
#             },
#             {
#                 "action": "order",
#                 "data": {
#                     "ticker": "AAPL",
#                     "quantity": 7,
#                     "price": 150.0,
#                     "order_type": "sell",
#                 },
#             },
#         ]

#         for order in orders:
#             await self.server_instance.message_handler.handle_message(
#                 order,
#                 self.server_instance.trading_system,
#                 self.server_instance.simulation_running,
#                 self.server_instance.realtime,
#             )

#         # Verify portfolio state
#         aapl_pos = self.server_instance.trading_system.portfolio.positions.get("AAPL")
#         assert aapl_pos is None

#         aapl_short = self.server_instance.trading_system.portfolio.short_positions.get(
#             "AAPL"
#         )
#         assert aapl_short is not None
#         assert aapl_short[0] == 2

#     async def test_simulation_reset(self):
#         """Test resetting the simulation"""
#         # Place an order to change state
#         buy_msg = {
#             "action": "order",
#             "data": {
#                 "ticker": "AAPL",
#                 "quantity": 10,
#                 "price": 155.0,
#                 "order_type": "buy",
#             },
#         }
#         await self.server_instance.message_handler.handle_message(
#             buy_msg,
#             self.server_instance.trading_system,
#             self.server_instance.simulation_running,
#             self.server_instance.realtime,
#         )

#         # Verify position exists
#         assert "AAPL" in self.server_instance.trading_system.portfolio.positions

#         # Reset simulation
#         await self.server_instance.reset()

#         # Verify positions are cleared
#         assert not self.server_instance.trading_system.portfolio.positions
