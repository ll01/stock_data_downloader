import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set, Union

import websockets
from websockets import ServerConnection

from stock_data_downloader.models import TickerData

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, max_in_flight_messages: int = 10):
        self.connections: Set[ServerConnection] = set()
        self.connection_queues: Dict[ServerConnection, asyncio.Queue] = {}
        self.error_counts: Dict[ServerConnection, int] = {}
        self.max_in_flight_messages = max_in_flight_messages
        self.MAX_RETRIES = 10

    async def add_connection(self, websocket: ServerConnection) -> None:
        self.connections.add(websocket)
        self.connection_queues[websocket] = asyncio.Queue(
            maxsize=self.max_in_flight_messages
        )
        self.error_counts[websocket] = 0
        asyncio.create_task(self._sender_task(websocket))
        logger.info(f"New connection from {websocket.remote_address}")

    async def remove_connection(self, websocket: ServerConnection) -> None:
        self.connections.discard(websocket)
        self.connection_queues.pop(websocket, None)
        self.error_counts.pop(websocket, None)
        logger.info(f"Connection from {websocket.remote_address} closed")


    async def _sender_task(self, websocket: ServerConnection) -> None:
        queue = self.connection_queues[websocket]
        while True:
            try:
                message: Dict[str, Any] = await queue.get()
                json_message = json.dumps(message, default=str)
                await websocket.send(json_message)
                queue.task_done()
            except websockets.ConnectionClosed:
                await self.remove_connection(websocket)
                break
            except Exception:
                logger.exception("Unexpected error in sender task")
                await self.remove_connection(websocket)
                break
            await asyncio.sleep(0.0001)

    async def send(
        self,
        websocket: ServerConnection,
        type: str,
        payload: Optional[Union[Dict[str, Any], List[Any]]] = None,
    ) -> None:
        """
        Enqueue a native-Python message. Handles both raw dictionaries and TickerData objects.
        """
        if websocket not in self.connection_queues:
            return  # already gone

        msg: Dict[str, Any] = {"type": type}
        if payload is not None:
            # Convert any TickerData objects to dictionaries
            if isinstance(payload, list) and type == "price_update":
                msg["data"] = [
                    item.model_dump(mode="json") if isinstance(item, TickerData) else item
                    for item in payload
                ]
            elif isinstance(payload, TickerData):
                msg["data"] = payload.model_dump(mode="json")
            else:
                msg["data"] = payload
        try:
            await self.connection_queues[websocket].put(msg)
        except asyncio.QueueFull:
            logger.warning("Client queue full; closing connection")
            await self.remove_connection(websocket)

    def increment_error_count(self, websocket: ServerConnection) -> int:
        self.error_counts[websocket] = self.error_counts.get(websocket, 0) + 1
        return self.error_counts[websocket]

    async def broadcast_to_all(
        self, type: str, payload: Optional[Any] = None
    ) -> None:
        if not self.connections:
            return

        tasks = [
            asyncio.create_task(self.send(ws, type, payload))
            for ws in list(self.connections)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)