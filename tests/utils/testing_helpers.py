
import asyncio
from typing import Callable, Any, Awaitable

def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except Exception:
        return False

async def wait_for(predicate: Callable[..., Any],
                   timeout: float = 2.0,
                   interval: float = 0.01):
    """Wait until predicate returns truthy. Predicate may be sync or async."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            result = predicate()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return result
        except Exception:
            # treat exceptions as not-ready; caller will see TimeoutError if it never becomes ready
            pass
        if loop.time() > deadline:
            raise TimeoutError(f"Condition not met within {timeout} seconds")
        await asyncio.sleep(interval)

async def wait_for_server_ready(server, timeout: float = 2.0):
    await wait_for(lambda: server.get_port() is not None and server.get_port() != 0, timeout=timeout)