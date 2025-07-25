import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set, Union

import websockets
from websockets import ServerConnection

# Assuming TickerData is defined elsewhere and has .model_dump()
class TickerData:
    def __init__(self, symbol: str, price: float):
        self.symbol = symbol
        self.price = price

    def model_dump(self, mode: str = "json"):
        return {"symbol": self.symbol, "price": self.price}

logger = logging.getLogger(__name__)

class SocketQueues:
    # These queues should be asyncio.Queue instances
    main: asyncio.Queue
    prio: asyncio.Queue

class ConnectionManager:
    def __init__(self, max_in_flight_messages: int = 10, max_prio_messages: int = 5):
        self.connections: Set[ServerConnection] = set()
        # Change connection_queues to store SocketQueues objects
        self.connection_queues: Dict[ServerConnection, SocketQueues] = {}
        self.error_counts: Dict[ServerConnection, int] = {}
        self.max_in_flight_messages = max_in_flight_messages
        self.max_prio_messages = max_prio_messages # New: Max size for priority queue
        self.MAX_RETRIES = 10

    async def add_connection(self, websocket: ServerConnection) -> None:
        self.connections.add(websocket)
        
        # Initialize both main and priority queues for each connection
        socket_queues = SocketQueues()
        socket_queues.main = asyncio.Queue(maxsize=self.max_in_flight_messages)
        socket_queues.prio = asyncio.Queue(maxsize=self.max_prio_messages) # Priority queue
        
        self.connection_queues[websocket] = socket_queues
        self.error_counts[websocket] = 0
        asyncio.create_task(self._sender_task(websocket))
        logger.info(f"New connection from {websocket.remote_address}")

    async def remove_connection(self, websocket: ServerConnection) -> None:
        self.connections.discard(websocket)
        # Pop the SocketQueues object
        if websocket in self.connection_queues:
            # Ensure queues are empty or tasks are done if necessary,
            # though removing the reference should allow garbage collection.
            del self.connection_queues[websocket] 
        self.error_counts.pop(websocket, None)
        logger.info(f"Connection from {websocket.remote_address} closed")

    async def _sender_task(self, websocket: ServerConnection) -> None:
        # Get both queues for this connection
        queues = self.connection_queues.get(websocket)
        if not queues:
            return # Connection already removed

        while True:
            try:
                message: Dict[str, Any]
                # Prioritize: Check priority queue first
                if not queues.prio.empty():
                    message = await queues.prio.get()
                    queues.prio.task_done()
                    logger.debug(f"Sending PRIORITY message to {websocket.remote_address}")
                else:
                    message = await queues.main.get()
                    queues.main.task_done()
                    logger.debug(f"Sending REGULAR message to {websocket.remote_address}")

                json_message = json.dumps(message, default=str)
                await websocket.send(json_message)
                
            except websockets.ConnectionClosed:
                logger.info(f"ConnectionClosed for {websocket.remote_address} in sender task.")
                await self.remove_connection(websocket)
                break
            except Exception:
                logger.exception(f"Unexpected error in sender task for {websocket.remote_address}")
                await self.remove_connection(websocket)
                break
            # Small sleep to prevent busy-waiting if queues are empty, though `await get()` handles this.
            # It's good practice if there are other operations in the loop.
            await asyncio.sleep(0.0001) 

    async def send(
        self,
        websocket: ServerConnection,
        type: str,
        payload: Optional[Union[Dict[str, Any], List[Any]]] = None,
        priority: bool = False, # New parameter to indicate priority
    ) -> None:
        """
        Enqueue a native-Python message. Handles both raw dictionaries and TickerData objects.
        Messages can be sent with priority.
        """
        if websocket not in self.connection_queues:
            return  # already gone

        queues = self.connection_queues[websocket]
        target_queue = queues.prio if priority else queues.main

        msg: Dict[str, Any] = {"type": type}
        if payload is not None:
            # Convert any TickerData objects to dictionaries
            if isinstance(payload, list) and type == "price_update":
                msg["data"] = [p.__dict__ for p in payload]
            elif isinstance(payload, TickerData):
                msg["data"] = [ payload.__dict__]
            else:
                msg["data"] = payload
        try:
            await target_queue.put(msg)
        except asyncio.QueueFull:
            logger.warning(
                f"Client {'priority' if priority else 'main'} queue full for {websocket.remote_address}; closing connection"
            )
            await self.remove_connection(websocket)

    def increment_error_count(self, websocket: ServerConnection) -> int:
        self.error_counts[websocket] = self.error_counts.get(websocket, 0) + 1
        return self.error_counts[websocket]

    async def broadcast_to_all(
        self, type: str, payload: Optional[Any] = None, priority: bool = False
    ) -> None:
        """
        Broadcasts a message to all connected clients, optionally with priority.
        """
        if not self.connections:
            return

        tasks = [
            asyncio.create_task(self.send(ws, type, payload, priority=priority))
            for ws in list(self.connections)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)