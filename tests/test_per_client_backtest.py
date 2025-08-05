import asyncio
import json
import pytest
import websockets
from stock_data_downloader.models import AppConfig, DataSourceConfig, BacktestDataSourceConfig, TickerConfig, GBMConfig
from stock_data_downloader.websocket_server.server import start_server

@pytest.mark.asyncio
async def test_two_clients_step_independently():
    # Build app config with backtest datasource
    tickers = {
        "AAA": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.01)),
        "BBB": TickerConfig(gbm=GBMConfig(mean=0.0, sd=0.02)),
    }
    bt_cfg = BacktestDataSourceConfig(
        backtest_model_type="gbm",
        ticker_configs=tickers,
        start_prices={"AAA": 100.0, "BBB": 200.0},
        timesteps=3,
        interval=1.0/252,
        seed=123,
    )
    app_cfg = AppConfig(
        data_source=DataSourceConfig(source_type="backtest", config=bt_cfg),
        exchange={"exchange": {"type": "test"}},
        server={},
        initial_cash=1000.0,
    )

    # Start server on random port
    uri = "ws://localhost:8765"
    stop_event = asyncio.Event()
    server_task = asyncio.create_task(start_server(app_cfg, websocket_uri=uri, stop_event=stop_event))
    await asyncio.sleep(0.2)

    async def connect_client():
        ws = await websockets.connect(uri)
        # drain initial messages (welcome, optional price_history)
        for _ in range(2):
            msg = json.loads(await ws.recv())
            if msg["type"] == "welcome":
                assert msg.get("data", {}).get("mode") == "pull" or msg.get("mode") == "pull"
                break
        # drain any extra non-action messages
        ws_messages = []
        ws_messages.append(msg)
        while True:
            try:
                nxt = await asyncio.wait_for(ws.recv(), timeout=0.05)
                m = json.loads(nxt)
                if m.get("type") in ("price_history",):
                    continue
                # push back by storing for later if needed
                ws_messages.append(m)
            except asyncio.TimeoutError:
                break
        return ws

    ws1 = await connect_client()
    ws2 = await connect_client()

    async def next_bar(ws):
        await ws.send(json.dumps({"action": "next_bar"}))
        # brief yield to let server enqueue response
        await asyncio.sleep(0)
        resp = json.loads(await ws.recv())
        return resp

    # Client 1 steps twice
    r11 = await next_bar(ws1)
    assert r11["type"] in ("price_update", "end_of_data")
    r12 = await next_bar(ws1)
    # Client 2 steps once
    r21 = await next_bar(ws2)
    assert r21["type"] in ("price_update", "end_of_data")

    # Step to end for both and ensure end_of_data reached
    await next_bar(ws1)
    end1 = await next_bar(ws1)
    assert end1["type"] in ("end_of_data", "simulation_end")

    # Step client 2 until termination to avoid timing flakiness
    end2 = None
    for _ in range(5):
        r = await next_bar(ws2)
        if r["type"] in ("end_of_data", "simulation_end"):
            end2 = r
            break
    assert end2 is not None

    await ws1.close()
    await ws2.close()
    # give server a moment to unwind handlers
    await asyncio.sleep(0.05)
    # stop server cleanly
    stop_event.set()
    await server_task
