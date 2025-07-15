import asyncio
import logging
import socket
from typing import Dict, Any

import websockets

from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.factories.DataSourceFactory import DataSourceFactory
from stock_data_downloader.websocket_server.factories.ExchangeFactory import ExchangeFactory
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.websocket_server.trading_system import TradingSystem


logger = logging.getLogger(__name__)


def find_free_port():
    """Finds a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))  # Bind to any available port
        return s.getsockname()[1]


async def create_server_from_config(config: Dict[str, Any]) -> WebSocketServer:
    """
    Create and configure a WebSocketServer from configuration
    
    Args:
        config: Server configuration dictionary
        
    Returns:
        Configured WebSocketServer instance
    """
    # Extract configurations
    exchange_config = config.get("exchange", {})
    data_source_config = config.get("data_source", {})
    server_config = config.get("server", {})
    simulation_config = config.get("simulation", {})
    
    # Determine if we're in simulation mode
    simulation_mode = simulation_config.get("enabled", True)
    
    # Create portfolio with initial cash
    initial_cash = simulation_config.get("initial_cash", 100000.0)
    portfolio = Portfolio(initial_cash=initial_cash)
    
    # Create exchange using factory
    exchange = ExchangeFactory.create_exchange(exchange_config, portfolio, simulation_mode)
    
    # Create data source using factory
    data_source = DataSourceFactory.create_data_source(data_source_config)
    
    # Create connection manager and message handler
    connection_manager = ConnectionManager()
    message_handler = MessageHandler()
    
    # Configure WebSocket server URI
    websocket_uri = server_config.get("uri")
    if not websocket_uri:
        port = server_config.get("port", find_free_port())
        host = server_config.get("host", "localhost")
        websocket_uri = f"ws://{host}:{port}"
    
    # Set up other server parameters
    realtime = not simulation_mode
    max_in_flight_messages = server_config.get("max_in_flight_messages", 10)
    
    # Create the TradingSystem
    trading_system = TradingSystem(
        exchange=exchange,
        portfolio=portfolio,
        data_source=data_source
    )

    # Create the WebSocket server
    server = WebSocketServer(
        trading_system=trading_system,
        connection_manager=connection_manager,
        message_handler=message_handler,
        uri=websocket_uri,
        max_in_flight_messages=max_in_flight_messages,
        realtime=realtime
    )
    
    return server


async def start_server_from_config(config: Dict[str, Any]):
    """
    Start a WebSocket server from configuration
    
    Args:
        config: Server configuration dictionary
    """
    # Create server from config
    server = await create_server_from_config(config)
    
    # Start the server
    # await server.start()
    
    # Extract server parameters
    server_config = config.get("server", {})
    websocket_uri = server.uri
    parts = websocket_uri.split("://")
    
    if len(parts) < 2 or ":" not in parts[-1]:
        raise ValueError("Invalid websocket URI format")
    
    host_port = parts[-1].split(":")
    host = host_port[0]
    port = int(host_port[1])
    logger.info(f"WebSocket server will run on {host}:{port}")
    # Configure ping interval based on mode
    simulation_mode = config.get("simulation", {}).get("enabled", True)
    ping_interval = None if simulation_mode else server_config.get("ping_interval", 20)
    ping_timeout = None if simulation_mode else server_config.get("ping_timeout", 20)
    
    logger.info(f"Starting {'Simulation' if simulation_mode else 'Live'} WebSocket server on {websocket_uri}")
    
    # Start the websockets server listener
    logger.debug(f"Starting WebSocket server on {websocket_uri} with ping interval {ping_interval} and timeout {ping_timeout}")
    async with websockets.serve(
        server.websocket_server,
        host,
        port,
        ping_interval=ping_interval,
        ping_timeout=ping_timeout,
    ):
        # The server will run until the loop is stopped
        logger.info(f"WebSocket server running on {websocket_uri}")
        logger.info("Server listener started. Press Ctrl+C to stop.")
        await asyncio.Future()  # Keep the server running indefinitely

    logger.info("Server stopped.")