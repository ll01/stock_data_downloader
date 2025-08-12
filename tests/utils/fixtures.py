import pytest
import asyncio
from unittest.mock import AsyncMock
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.server import WebSocketServer

async def _wait_for_server_ready(server, timeout=2.0):
    """Poll the server until it reports a non-zero port (or timeout)."""
    loop = asyncio.get_event_loop()
    start = loop.time()
    while True:
        try:
            port = server.get_port()
            if port:
                return
        except Exception:
            # server not ready yet
            pass
        if loop.time() - start > timeout:
            raise TimeoutError("Server did not become ready within timeout")
        await asyncio.sleep(0.01)

@pytest.fixture
async def websocket_server():
    """
    Improved websocket_server fixture:
    - Ensures nested data_source is an AsyncMock to avoid attribute errors.
    - Waits for server readiness instead of relying on implicit timing.
    - Performs a best-effort shutdown with a timeout to avoid test-process hangs.
    """
    ts = AsyncMock()
    ts.data_source = AsyncMock()
    ts.data_source.get_next_bar_for_client = AsyncMock(return_value={"c": 999})
    cm = ConnectionManager()
    mh = MessageHandler()
    # Use 127.0.0.1 instead of localhost to avoid Windows issues
    server = WebSocketServer(ts, cm, mh, "ws://127.0.0.1:0")

    await server.start()
    await _wait_for_server_ready(server)

    port = server.get_port()
    try:
        yield server, port
    finally:
        # best-effort shutdown with timeout to prevent hanging tests
        try:
            await asyncio.wait_for(server.shutdown(), timeout=5.0)
        except Exception:
            # swallow exceptions during teardown to avoid masking test failures
            pass