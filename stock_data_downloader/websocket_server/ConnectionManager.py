import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set, Union

import websockets
from websockets import ServerConnection

from stock_data_downloader.models import TickerData

logger = logging.getLogger(__name__)

class SocketQueues:
    # These queues should be asyncio.Queue instances
    main: asyncio.Queue

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
        queue = self.connection_queues[websocket].main

        while True:
            try:
                message = await queue.get()
                queue.task_done()
                logger.debug(f"Sending message to {websocket.remote_address}")
                
                json_message = json.dumps(message, default=str)
                await websocket.send(json_message)
            except websockets.ConnectionClosed:
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
            logging.warning("attempted to send to socket server has lost connection to")
            return  # already gone

        queues = self.connection_queues[websocket]
        target_queue = queues.main

        msg: Dict[str, Any] = {"type": type}
        if payload is not None:
            # Convert any TickerData objects to dictionaries
            if isinstance(payload, list) and type == "price_update":
                # Check if the items are TickerData objects (Pydantic BaseModel)
                if payload and isinstance(payload[0], TickerData):
                    msg["data"] = [p.model_dump() for p in payload]
                else:
                    # Handle case where items might already be dictionaries
                    msg["data"] = payload
            elif isinstance(payload, TickerData):
                msg["data"] = [payload.model_dump()]
            else:
                msg["data"] = payload
        try:
            await target_queue.put(msg)
        except asyncio.QueueFull:
            logger.warning(
                f"Client {'priority' if priority else 'main'} queue full for {websocket.remote_address}; closing connection"
            )
            await self.remove_connection(websocket)
        except Exception as e:
            logging.warning(f"failing to send message to queue {e}", exc_info=True)

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