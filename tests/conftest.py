import asyncio
import socket
import pytest
from typing import Callable, Any, Awaitable

# Small helpers and fixtures for event-driven testing

def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
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

@pytest.fixture
def stop_event():
    """Provides an asyncio.Event tests can use to signal background tasks to stop."""
    return asyncio.Event()

@pytest.fixture(autouse=True)
def _noop_for_sync_tests():
    """No-op autouse fixture for synchronous tests (keeps behavior consistent)."""
    return

@pytest.fixture(autouse=True)
async def preserve_async_tasks():
    """Best-effort cancellation of user-created background tasks.

    This fixture cancels any tasks created during the test but does not await their
    completion. Awaiting teardown of arbitrary tasks can interfere with pytest's own
    fixture finalizers; to keep teardown robust we perform non-blocking cancellation only.
    """
    before = set(asyncio.all_tasks())
    yield
    after = set(asyncio.all_tasks())
    new = after - before
    if not new:
        return

    current = asyncio.current_task()

    for t in new:
        # Never cancel the current task
        if t is current:
            continue
        # Heuristic: avoid canceling pytest/finalizer internals by inspecting coroutine name
        coro = getattr(t, "get_coro", lambda: None)()
        try:
            cname = getattr(coro, "__qualname__", "") or getattr(coro, "__name__", "") or repr(coro)
        except Exception:
            cname = repr(coro)
        if "_wrap_asyncgen_fixture" in cname or "finalizer" in cname or "pytest" in cname:
            continue
        try:
            if not t.done():
                t.cancel()
        except Exception:
            # ignore cancellation errors
            pass

    # Do not await canceled tasks here to avoid interfering with pytest teardown.
    return

# Expose helpers to tests via pytest namespace
def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: mark test as end-to-end (slow)")

# Make helper functions importable from tests via pytest namespace if desired
pytest.wait_for = wait_for
pytest.wait_for_server_ready = wait_for_server_ready
pytest.is_port_open = is_port_open