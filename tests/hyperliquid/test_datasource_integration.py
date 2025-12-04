import os
import asyncio
import pytest

from stock_data_downloader.models import HyperliquidDataSourceConfig, DataSourceConfig
from stock_data_downloader.websocket_server.DataSource.HyperliquidDataSource import HyperliquidDataSource

pytestmark = pytest.mark.skipif(
    not (os.getenv("HL_WALLET_ADDRESS") and os.getenv("HL_SECRET_KEY")),
    reason="Hyperliquid credentials not provided; skipping integration test",
)

@pytest.mark.asyncio
async def test_hyperliquid_subscribe_minimal():
    cfg = HyperliquidDataSourceConfig(
        source_type="hyperliquid",
        network=os.getenv("HYPERLIQUID_NETWORK", "testnet"),
        tickers=[os.getenv("HL_TEST_TICKER", "BTC")],
        interval="1m",
        api_config={
            "wallet_address": os.getenv("HL_WALLET_ADDRESS"),
            "secret_key": os.getenv("HL_SECRET_KEY"),
        },
    )
    ds = HyperliquidDataSource(config=cfg.api_config, network=cfg.network, tickers=cfg.tickers, interval=cfg.interval)

    received = []

    async def cb(kind, payload):
        if kind == "price_update":
            received.extend(payload)

    await ds.subscribe_realtime_data(cb)
    try:
        # wait for a few messages
        for _ in range(10):
            if received:
                break
            await asyncio.sleep(0.5)
        assert received, "Did not receive any price updates from Hyperliquid"
    finally:
        await ds.unsubscribe_realtime_data()
