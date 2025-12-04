import asyncio
import logging
import os
import socket
from typing import Dict, Any

import websockets

from stock_data_downloader.models import AppConfig
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.SimulationManager import SimulationManager
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


async def create_server_from_config(config: AppConfig) -> WebSocketServer:
    """
    Create and configure a WebSocketServer from configuration
    
    Args:
        config: AppConfig object with structured configuration
        
    Returns:
        Configured WebSocketServer instance
    """
    # Create portfolio with initial cash from config
    portfolio = Portfolio(initial_cash=config.initial_cash)
    
    # For now, assume simulation mode (test exchange) since we don't have exchange config in AppConfig
    # This could be extended in the future to support different exchange types

    
    # Create exchange using factory
    exchange = ExchangeFactory.create_exchange(config.exchange, portfolio)
    
    # Create data source using factory
    data_source = DataSourceFactory.create_data_source(config.data_source)
    
    # Create connection manager and message handler
    connection_manager = ConnectionManager()
    message_handler = MessageHandler()
    
    # Configure WebSocket server URI from server config
    server_config = config.server
    websocket_uri = f"ws://{server_config.data_downloader.host}:{ server_config.data_downloader.port}"
    logger.info(f"WebSocket server will run on {websocket_uri}")
    # Create the TradingSystem
    trading_system = TradingSystem(
        exchange=exchange,
        portfolio=portfolio,
        data_source=data_source
    )

    # Create the SimulationManager
    simulation_manager = SimulationManager(config)

    # Create the WebSocket server
    server = WebSocketServer(
        data_source=data_source,
        connection_manager=connection_manager,
        message_handler=message_handler,
        simulation_manager=simulation_manager,
        uri=websocket_uri,
        max_in_flight_messages=10,  # Default value
    )
    
    return server


async def start_server_from_config(config: AppConfig):
    """
    Start a WebSocket server from configuration
    
    Args:
        config: AppConfig object with structured configuration
    """
    # Create server from config
    server = await create_server_from_config(config)
    
    # Extract server parameters
    server_config = config.server
    websocket_uri = server.uri
    parts = websocket_uri.split("://")
    
    if len(parts) < 2 or ":" not in parts[-1]:
        raise ValueError("Invalid websocket URI format")
    
    host_port = parts[-1].split(":")
    host = host_port[0]
    port = int(host_port[1])
    
    # Configure ping interval based on mode
    simulation_mode = config.data_source.source_type == "backtest"  # Assume backtest = simulation mode
    ping_interval = None if simulation_mode else server_config.ping_interval
    ping_timeout = None if simulation_mode else server_config.ping_timeout
    
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