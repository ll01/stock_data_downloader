import asyncio
import json
import logging
from typing import Any, Dict, Set
from websockets import ServerConnection
import websockets


class ConnectionManager:
    def __init__(self, max_in_flight_messages: int = 10):
        self.connections: Set[ServerConnection] = set()
        self.connection_queues: Dict[ServerConnection, asyncio.Queue] = {}
        self.error_counts: Dict[ServerConnection, int] = {}
        self.max_in_flight_messages = max_in_flight_messages
        self.MAX_RETRIES = 10


    async def add_connection(self, websocket: ServerConnection):
        self.connections.add(websocket)
        queue = asyncio.Queue(maxsize=self.max_in_flight_messages)
        self.connection_queues[websocket] = queue
        self.error_counts[websocket] = 0  # Initialize error count
        # Start a sender task for this connection
        asyncio.create_task(self._sender_task(websocket, queue))
        logging.info(f"New connection from {websocket.remote_address}")

    async def remove_connection(self, websocket: ServerConnection):
        if websocket in self.connections:
            if websocket in self.connection_queues:
                # You might want to await the queue to empty or cancel pending tasks
                del self.connection_queues[websocket]
            if websocket in self.error_counts:
                del self.error_counts[websocket]
            self.connections.remove(websocket)
            logging.info(f"Connection from {websocket.remote_address} closed")

    async def _sender_task(self, websocket: ServerConnection, queue: asyncio.Queue):
        while True:
            try:
                message = await queue.get()
                await websocket.send(message)
                queue.task_done()
            except websockets.ConnectionClosed:
                await self.remove_connection(websocket)
                break

    async def send(
        self, websocket: ServerConnection, type: str, payload: Any = None, retry_count=0
    ):
        msg = {"type": type}
        if payload is not None:
            msg["payload"] = payload
        try:
            # Add message to the client-specific queue
            await self.connection_queues[websocket].put(json.dumps(msg))
        except asyncio.QueueFull:
            if retry_count >= self.MAX_RETRIES:
                # Handle queue overflow (e.g., disconnect slow client)
                logging.warning("Client message queue full; closing connection")
                await self.remove_connection(websocket)
                return
            await asyncio.sleep(10)
            retry_count += 1
            await self.send(websocket, type, payload, retry_count)

    def increment_error_count(self, websocket: ServerConnection):
        if websocket in self.error_counts:
            self.error_counts[websocket] += 1
        else:
            self.error_counts[websocket] = 1
        return self.error_counts[websocket]

    def get_error_count(self, websocket: ServerConnection) -> int:
        return self.error_counts.get(websocket, 0)

    async def broadcast_to_all(self, type: str, payload: Any = None):
        """Send data to all connected clients."""
        if not self.connections:
            return

        tasks = []
        disconnected = set()

        for websocket in self.connections:
            try:
                # Create a task for each send operation
                task = asyncio.create_task(self.send(websocket, type, payload))
                tasks.append(task)
            except Exception as e:
                logging.error(f"Error creating send task: {e}")
                disconnected.add(websocket)

        # Wait for all send tasks to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Remove disconnected clients
        for websocket in disconnected:
            if websocket in self.connections:
                await self.remove_connection(websocket)