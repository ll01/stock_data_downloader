import pytest
import asyncio
from stock_data_downloader.websocket_server.ConnectionManager import ConnectionManager

class DummyWebSocket:
    """Lightweight websocket stub used for unit tests.
    - records messages sent via async send()
    - exposes an asyncio.Event to wait deterministically for outgoing messages
    """
    def __init__(self):
        self.remote_address = ("127.0.0.1", 12345)
        self.request_headers = {}
        self.messages = []
        self._event = asyncio.Event()
        self.closed = False

    async def send(self, message: str):
        self.messages.append(message)
        # set the event so tests can await the send without sleeps
        self._event.set()

    async def close(self):
        self.closed = True

    async def wait_for_message(self, timeout: float = 1.0):
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        return list(self.messages)

@pytest.mark.asyncio
async def test_add_connection_assigns_id():
    cm = ConnectionManager()
    ws = DummyWebSocket()
    await cm.add_connection(ws)

    client_id = cm.get_client_id(ws)
    # ConnectionManager uses UUIDs for client ids; ensure a non-empty string is returned
    assert isinstance(client_id, str) and client_id

    # get_socket should return the same websocket for the client id
    assert cm.get_socket(client_id) == ws

    # Wait for the welcome message to be sent via sender task (deterministic via event)
    messages = await ws.wait_for_message(timeout=1.0)
    assert messages, "Expected at least one outgoing message (welcome)"
    assert "welcome" in messages[0]

@pytest.mark.asyncio
async def test_remove_connection_cleans_state():
    cm = ConnectionManager()
    ws = DummyWebSocket()
    await cm.add_connection(ws)
    assert ws in cm.connections

    await cm.remove_connection(ws)
    assert ws not in cm.connections
    assert cm.get_client_id(ws) is None
    assert ws not in cm.connection_info

@pytest.mark.asyncio
async def test_increment_error_count_updates_stats():
    cm = ConnectionManager()
    ws = DummyWebSocket()
    await cm.add_connection(ws)

    prev_errors = cm.stats.get("errors", 0)
    cnt1 = cm.increment_error_count(ws)
    cnt2 = cm.increment_error_count(ws)

    assert cnt1 == 1
    assert cnt2 == 2
    assert cm.get_error_count(ws) == 2
    assert cm.stats["errors"] >= prev_errors + 2