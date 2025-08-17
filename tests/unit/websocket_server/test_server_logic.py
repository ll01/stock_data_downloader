import pytest
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from stock_data_downloader.websocket_server.server import WebSocketServer
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
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
        # signal that a message was sent
        self._event.set()

    async def close(self):
        self.closed = True

    async def wait_for_message(self, timeout: float = 1.0):
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        # reset event for subsequent waits
        self._event.clear()
        return list(self.messages)

@pytest.mark.asyncio
async def test_reset_single_client():
    cm = ConnectionManager()
    ws = DummyWebSocket()
    await cm.add_connection(ws)

    # Wait for welcome message produced by add_connection sender task
    await ws.wait_for_message(timeout=1.0)
    # clear messages so we only observe messages produced by reset
    ws.messages.clear()

    data_source = AsyncMock()
    data_source.reset_client = AsyncMock()
    data_source.reset = AsyncMock()
    portfolio = MagicMock()
    portfolio.clear_positions = MagicMock()

    trading_system = SimpleNamespace(data_source=data_source, portfolio=portfolio)
    message_handler = MessageHandler()
    server = WebSocketServer(trading_system, cm, message_handler, "ws://localhost:0")

    client_id = cm.get_client_id(ws)
    assert client_id is not None

    await server.reset(initiating_websocket=ws)
    
    # ensure data_source.reset_client was called for the client;
    # do not clear global portfolio on single-client reset
    data_source.reset_client.assert_awaited()
    portfolio.clear_positions.assert_not_called()
    # check that a reset message was sent to this websocket
    messages = await ws.wait_for_message(timeout=1.0)
    assert messages, "Expected a reset message to be sent"
    # parse and assert message contents
    last_msg = messages[-1]
    parsed = json.loads(last_msg)
    assert parsed.get("type") == "reset"
    assert "Client simulation has been reset" in parsed.get("data", {}).get("message", "") or "Client simulation" in str(parsed.get("data"))

@pytest.mark.asyncio
async def test_reset_all_clients():
    cm = ConnectionManager()
    ws1 = DummyWebSocket()
    ws2 = DummyWebSocket()
    await cm.add_connection(ws1)
    await cm.add_connection(ws2)

    # consume welcome messages
    await ws1.wait_for_message(timeout=1.0)
    await ws2.wait_for_message(timeout=1.0)
    ws1.messages.clear()
    ws2.messages.clear()

    data_source = AsyncMock()
    data_source.reset = AsyncMock()
    portfolio = MagicMock()
    portfolio.clear_positions = MagicMock()

    trading_system = SimpleNamespace(data_source=data_source, portfolio=portfolio)
    message_handler = MessageHandler()
    server = WebSocketServer(trading_system, cm, message_handler, "ws://localhost:0")

    await server.reset()

    # both clients should receive reset message
    msgs1 = await ws1.wait_for_message(timeout=1.0)
    msgs2 = await ws2.wait_for_message(timeout=1.0)
    assert msgs1 and msgs2

    parsed1 = json.loads(msgs1[-1])
    parsed2 = json.loads(msgs2[-1])
    assert parsed1.get("type") == "reset"
    assert parsed2.get("type") == "reset"

    data_source.reset.assert_awaited()
    portfolio.clear_positions.assert_called_once()