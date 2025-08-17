import asyncio
import json
import logging
import inspect
from typing import Any, Dict, List, Optional, Set, Union, Callable
import uuid
from datetime import datetime, timezone

import websockets
from websockets import ServerConnection

from stock_data_downloader.models import TickerData

logger = logging.getLogger(__name__)

class SocketQueues:
    # These queues should be asyncio.Queue instances
    main: asyncio.Queue
    prio: asyncio.Queue  # priority queue (sent before main)

    def empty(self) -> bool:
        """Check if both queues are empty."""
        main_empty = self.main.empty() if hasattr(self, "main") and self.main is not None else True
        prio_empty = self.prio.empty() if hasattr(self, "prio") and self.prio is not None else True
        return main_empty and prio_empty
        
    def qsize(self) -> int:
        """Get the combined size of the queues."""
        main_q = self.main.qsize() if hasattr(self, "main") and self.main is not None else 0
        prio_q = self.prio.qsize() if hasattr(self, "prio") and self.prio is not None else 0
        return main_q + prio_q
        
    async def get(self):
        """Prefer priority queue items when available."""
        if hasattr(self, "prio") and self.prio is not None and not self.prio.empty():
            return await self.prio.get()
        return await self.main.get()
        
    def task_done(self, prio: bool = False):
        """Mark a task as done for the given queue."""
        if prio and hasattr(self, "prio") and self.prio is not None:
            self.prio.task_done()
        else:
            self.main.task_done()

class ConnectionManager:
    def __init__(self, max_in_flight_messages: int = 10, max_prio_messages: int = 5, max_error_threshold: int = 5, start_health_check: bool = True):
        """
        Initialize the ConnectionManager.

        Args:
            max_in_flight_messages: Maximum messages allowed in the main queue per connection.
            max_prio_messages: (Reserved for future priority queue support).
            max_error_threshold: Maximum number of errors before a connection is considered unhealthy.
            start_health_check: Whether to enable health check background tasks.
        """
        self.connections: Set[ServerConnection] = set()
        self.connection_queues: Dict[ServerConnection, SocketQueues] = {}
        self.error_counts: Dict[ServerConnection, int] = {}
        self.connection_info: Dict[ServerConnection, Dict] = {}
        # Stats track both current and cumulative metrics
        self.stats = {
            "active_connections": 0,
            "total_connections": 0,
            "messages_sent": 0,
            "errors": 0,
        }
        self.sender_tasks: Dict[ServerConnection, asyncio.Task] = {}
        self.max_in_flight_messages = max_in_flight_messages
        self.max_prio_messages = max_prio_messages
        self.MAX_ERROR_THRESHOLD = max_error_threshold
        self.start_health_check = start_health_check
        self.MAX_RETRIES = 10
        self._client_ids: Dict[ServerConnection, str] = {}
        self._sockets_by_client: Dict[str, ServerConnection] = {}
        # Track which clients have been sent final reports for the current simulation run.
        # This attribute used to be dynamically attached by the server; make it explicit
        # on ConnectionManager so static type checkers (Pylance) do not warn.
        self._final_report_sent: Set[str] = set()

    async def add_connection(self, websocket: ServerConnection, enqueue_welcome: bool = True) -> None:
        """
        Add a websocket connection. By default a welcome message is enqueued,
        but callers (e.g. the server) can set enqueue_welcome=False to avoid
        automatic welcome messages when they prefer to control initial ordering.
        """
        self.connections.add(websocket)

        # Initialize both main and priority queues for each connection
        socket_queues = SocketQueues()
        socket_queues.main = asyncio.Queue(maxsize=self.max_in_flight_messages)
        socket_queues.prio = asyncio.Queue(maxsize=self.max_prio_messages)

        self.connection_queues[websocket] = socket_queues
        self.error_counts[websocket] = 0
        client_id = str(uuid.uuid4())
        # extract user agent if available
        user_agent = None
        try:
            headers = getattr(websocket, "request_headers", {}) or {}
            user_agent = headers.get("User-Agent") or headers.get("user-agent")
        except Exception:
            user_agent = None

        self.connection_info[websocket] = {
            "remote_address": websocket.remote_address,
            "connected_at": asyncio.get_event_loop().time(),
            "client_id": client_id,
            "messages_sent": 0,
            "user_agent": user_agent,
        }
        self._client_ids[websocket] = client_id
        self._sockets_by_client[client_id] = websocket
        self.stats["active_connections"] += 1
        self.stats["total_connections"] = self.stats.get("total_connections", 0) + 1

        # Start sender task
        task = asyncio.create_task(self._sender_task(websocket))
        self.sender_tasks[websocket] = task

        # Queue a welcome message so tests can observe initial queue state (optional)
        if enqueue_welcome:
            try:
                welcome = json.dumps(
                    {
                        "type": "welcome",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "client_id": client_id,
                    },
                    default=str,
                )
                # Best-effort put into main queue; if queue full, ignore
                try:
                    socket_queues.main.put_nowait(welcome)
                except asyncio.QueueFull:
                    logger.debug("Welcome message queue full on add_connection")
            except Exception:
                logger.debug("Failed to enqueue welcome message", exc_info=True)

        logger.info(f"New connection from {websocket.remote_address}, client_id: {client_id}")

    async def remove_connection(self, websocket: ServerConnection) -> None:
        # Attempt to close websocket connection first (handle sync/async close)
        try:
            if hasattr(websocket, "close"):
                maybe_close = websocket.close
                try:
                    res = maybe_close()
                    if inspect.isawaitable(res):
                        await res
                except TypeError:
                    # Not callable or other issue; ignore
                    pass
        except Exception:
            # Best-effort close; ignore errors
            try:
                res2 = websocket.close()
                if inspect.isawaitable(res2):
                    await res2
            except Exception:
                pass

        self.connections.discard(websocket)
        # Pop the SocketQueues object
        if websocket in self.connection_queues:
            del self.connection_queues[websocket]
        self.error_counts.pop(websocket, None)
        # remove client id mapping
        client_id = self._client_ids.pop(websocket, None)
        if client_id:
            self._sockets_by_client.pop(client_id, None)
        # remove connection info
        if websocket in self.connection_info:
            del self.connection_info[websocket]
        self.stats["active_connections"] = max(0, self.stats["active_connections"] - 1)
        
        # Cancel the sender task
        if websocket in self.sender_tasks:
            self.sender_tasks[websocket].cancel()
            del self.sender_tasks[websocket]
            
        logger.info(f"Connection from {getattr(websocket, 'remote_address', None)} closed")

    def assign_client_id(self, websocket: ServerConnection) -> str:
        # This method is now handled in add_connection
        if websocket in self._client_ids:
            return self._client_ids[websocket]
        client_id = str(uuid.uuid4())
        self._client_ids[websocket] = client_id
        self._sockets_by_client[client_id] = websocket
        if websocket in self.connection_info:
            self.connection_info[websocket]["client_id"] = client_id
        return client_id

    def update_connection_info(self, websocket: ServerConnection, info: Dict):
        """Update connection info for a websocket"""
        if websocket in self.connection_info:
            self.connection_info[websocket].update(info)
        else:
            self.connection_info[websocket] = info
        # Ensure client_id is always set
        if "client_id" not in self.connection_info[websocket]:
            self.connection_info[websocket]["client_id"] = self._client_ids.get(websocket, "")

    def get_client_id(self, websocket: ServerConnection) -> Optional[str]:
        return self._client_ids.get(websocket)

    def get_socket(self, client_id: str) -> Optional[ServerConnection]:
        return self._sockets_by_client.get(client_id)

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

        NOTE: sanitize outgoing payloads to remove internal runtime objects
        (e.g., the live websocket under "_ws" or internal fields starting with "_")
        so we never leak non-serializable objects into the send queue or logs.
        """
        if websocket not in self.connection_queues:
            logging.warning("attempted to send to socket server has lost connection to")
            return  # already gone

        queues = self.connection_queues[websocket]
        target_queue = queues.prio if priority else queues.main

        def _sanitize(obj):
            # Recursively remove private/internal keys and replace live socket objects
            if isinstance(obj, dict):
                out = {}
                for k, v in obj.items():
                    # drop keys that are clearly internal
                    if isinstance(k, str) and k.startswith("_"):
                        continue
                    out[k] = _sanitize(v)
                return out
            if isinstance(obj, list):
                return [_sanitize(x) for x in obj]
            # Detect websocket-like objects by common attribute and replace with a string
            if hasattr(obj, "remote_address") and hasattr(obj, "send"):
                try:
                    return f"<ServerConnection {getattr(obj, 'remote_address', '')}>"
                except Exception:
                    return "<ServerConnection>"
            return obj

        msg: Dict[str, Any] = {"type": type, "timestamp": datetime.now(timezone.utc).isoformat()}
        if payload is not None:
            # Convert any TickerData objects to dictionaries
            if isinstance(payload, list) and type == "price_update":
                # Check if the items are TickerData objects (Pydantic BaseModel)
                if payload and isinstance(payload[0], TickerData):
                    msg["data"] = [p.model_dump() for p in payload]
                else:
                    # Handle case where items might already be dictionaries
                    msg["data"] = _sanitize(payload)
            elif isinstance(payload, TickerData):
                msg["data"] = [payload.model_dump()]
            else:
                msg["data"] = _sanitize(payload)
        # Always enqueue serialized JSON strings so tests can inspect the messages directly
        try:
            json_msg = json.dumps(msg, default=str)
            # Put respecting priority queue
            await target_queue.put(json_msg)
        except asyncio.QueueFull:
            logger.warning(
                f"Client {'priority' if priority else 'main'} queue full for {getattr(websocket, 'remote_address', None)}; closing connection"
            )
            await self.remove_connection(websocket)
        except Exception as e:
            logging.warning(f"failing to send message to queue {e}", exc_info=True)

    def increment_error_count(self, websocket: ServerConnection) -> int:
        self.error_counts[websocket] = self.error_counts.get(websocket, 0) + 1
        self.stats["errors"] += 1
        return self.error_counts[websocket]
        
    def get_error_count(self, websocket: ServerConnection) -> int:
        return self.error_counts.get(websocket, 0)
        
    async def shutdown(self):
        """Gracefully shutdown the connection manager"""
        # First cancel all sender tasks
        if self.sender_tasks:
            tasks_to_cancel = list(self.sender_tasks.values())
            for task in tasks_to_cancel:
                task.cancel()
            
            # Wait for cancellation to propagate
            await asyncio.wait(tasks_to_cancel, timeout=0.2)
        
        self.sender_tasks.clear()
        
        # Then remove all connections
        connections = list(self.connections)
        if connections:
            remove_tasks = [self.remove_connection(conn) for conn in connections]
            await asyncio.gather(*remove_tasks, return_exceptions=True)
        
        # Clear all collections
        self.connections.clear()
        self.connection_queues.clear()
        self.error_counts.clear()
        self.connection_info.clear()
        self._client_ids.clear()
        self._sockets_by_client.clear()
        
        logger.info(f"ConnectionManager shutdown complete. Closed {len(connections)} connections")
        
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        # Create a new dictionary with float values for all stats
        stats_copy = {
            key: float(value) if isinstance(value, int) else value
            for key, value in self.stats.items()
        }
        
        try:
            now = asyncio.get_event_loop().time()
            uptimes = []
            for ws_info in self.connection_info.values():
                connected_at = ws_info.get("connected_at")
                if connected_at:
                    uptimes.append(now - connected_at)
            uptime_seconds = max(uptimes) if uptimes else 0.0
            stats_copy["uptime_seconds"] = uptime_seconds
            stats_copy["messages_per_second"] = (
                stats_copy.get("messages_sent", 0.0) / uptime_seconds
                if uptime_seconds > 0
                else 0.0
            )
        except Exception:
            stats_copy["uptime_seconds"] = 0.0
            stats_copy["messages_per_second"] = 0.0
        return stats_copy

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
        
    async def broadcast_by_filter(self, type: str, payload: Dict[str, Any], filter_func: Callable[[Dict], bool]):
        """Broadcast a message to clients matching the filter"""
        for websocket in list(self.connections):
            if websocket in self.connection_info and filter_func(self.connection_info[websocket]):
                await self.send(websocket, type, payload)
                
    async def _sender_task(self, websocket: ServerConnection) -> None:
        """Background task that sends messages from the queue to the websocket."""
        if websocket not in self.connection_queues:
            logger.debug("No connection queues for websocket, exiting sender task")
            return

        queues = self.connection_queues[websocket]
        main_q = queues.main
        prio_q = getattr(queues, "prio", None)

        try:
            while True:
                try:
                    prio_used = False
                    message = None
                    # Prefer priority queue if available
                    if prio_q is not None:
                        try:
                            message = prio_q.get_nowait()
                            prio_used = True
                        except asyncio.QueueEmpty:
                            # Give other coroutines a chance to enqueue priority messages
                            # before we block waiting on the main queue. This reduces race
                            # conditions where a main-queue "welcome" message would be
                            # delivered before a just-enqueued priority response.
                            await asyncio.sleep(0)
                            try:
                                message = prio_q.get_nowait()
                                prio_used = True
                            except asyncio.QueueEmpty:
                                # no prio messages, fall through to main queue
                                message = await asyncio.wait_for(main_q.get(), timeout=0.1)
                                prio_used = False
                    else:
                        message = await asyncio.wait_for(main_q.get(), timeout=0.1)
                        prio_used = False

                    # Mark task as done
                    if prio_used and prio_q is not None:
                        prio_q.task_done()
                    else:
                        main_q.task_done()

                    # Serialize if needed
                    if not isinstance(message, str):
                        json_message = json.dumps(message, default=str)
                    else:
                        json_message = message

                    # Send the message
                    await websocket.send(json_message)

                    # Update stats
                    if websocket in self.connection_info:
                        self.connection_info[websocket]["messages_sent"] = self.connection_info[websocket].get("messages_sent", 0) + 1
                    self.stats["messages_sent"] = self.stats.get("messages_sent", 0) + 1
                except asyncio.TimeoutError:
                    # Check if connection should be closed
                    if websocket not in self.connections:
                        break
                    continue
                except asyncio.CancelledError:
                    break
                except websockets.ConnectionClosed:
                    if websocket in self.connections:
                        await self.remove_connection(websocket)
                    break
                except Exception as e:
                    logger.error(f"Error in sender task: {e}", exc_info=True)
                    if websocket in self.connections:
                        await self.remove_connection(websocket)
                    break
        finally:
            # Ensure the task is removed from sender_tasks
            if websocket in self.sender_tasks:
                del self.sender_tasks[websocket]
            logger.debug(f"Sender task for {getattr(websocket, 'remote_address', None)} completed")