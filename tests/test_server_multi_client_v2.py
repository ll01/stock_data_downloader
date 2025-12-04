import asyncio
import json
import multiprocessing
import time

import pytest
import websockets

from stock_data_downloader.models import AppConfig, ServerConfig, ExchangeConfig, TestExchangeConfig, DataSourceConfig, BacktestDataSourceConfig
from stock_data_downloader.websocket_server.server import find_free_port, start_server

def server_process(config, uri, stop_flag):
    asyncio.run(start_server(config, uri, stop_flag))

@pytest.fixture
def test_config():
    """Provides a basic config for testing."""
    return AppConfig(
        server=ServerConfig(),
        initial_cash=100_000.0,
        exchange=ExchangeConfig(
            exchange=TestExchangeConfig(type='test', maker_fee_bps=1.0, taker_fee_bps=3.5, slippage_bps=5.0)
        ),
        data_source=DataSourceConfig(
            source_type='backtest',
            config=BacktestDataSourceConfig(
                source_type='backtest',
                backtest_model_type='gbm',
                timesteps=10,
                interval=0.1,
                ticker_configs={},
                start_prices={'AAPL': 150.0}
            )
        )
    )

@pytest.mark.asyncio
async def test_multi_client_state_isolation(test_config):
    """Tests that two clients have isolated portfolio state."""
    port = find_free_port()
    uri = f"ws://127.0.0.1:{port}"
    stop_flag = multiprocessing.Value("b", False)

    process = multiprocessing.Process(target=server_process, args=(test_config, uri, stop_flag))
    process.start()

    time.sleep(2) # Give the server time to start

    try:
        client_a = await websockets.connect(uri)
        client_b = await websockets.connect(uri)

        async def send_and_wait(ws, msg, expected_type):
            await ws.send(json.dumps(msg))
            while True:
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get("type") == expected_type:
                    return raw

        order_a = {
            "action": "order",
            "data": {
                "ticker": "AAPL",
                "quantity": 10,
                "price": 150,
                "order_type": "buy"
            }
        }
        raw_a = await send_and_wait(client_a, order_a, "order_confirmation")
        resp_a = json.loads(raw_a)
        assert resp_a["type"] == "order_confirmation"

        order_b = {
            "action": "order",
            "data": {
                "ticker": "AAPL",
                "quantity": 5,
                "price": 150,
                "order_type": "buy"
            }
        }
        raw_b = await send_and_wait(client_b, order_b, "order_confirmation")
        resp_b = json.loads(raw_b)
        assert resp_b["type"] == "order_confirmation"

        final_a_raw = await send_and_wait(client_a, {"action": "final_report"}, "final_report")
        final_a = json.loads(final_a_raw)
        
        final_b_raw = await send_and_wait(client_b, {"action": "final_report"}, "final_report")
        final_b = json.loads(final_b_raw)

        pos_a = final_a["data"]["portfolio"]["positions"]["AAPL"]
        assert pos_a[0] == 10
        assert abs(pos_a[1] - 150.0) < 1.0
        
        pos_b = final_b["data"]["portfolio"]["positions"]["AAPL"]
        assert pos_b[0] == 5
        assert abs(pos_b[1] - 150.0) < 1.0
        
        assert abs(final_a["data"]["portfolio"]["cash"] - (100_000.0 - 10 * 150)) < 10
        assert abs(final_b["data"]["portfolio"]["cash"] - (100_000.0 - 5 * 150)) < 10

        await client_a.close()
        await client_b.close()

    finally:
        stop_flag.value = True
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
