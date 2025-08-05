import os
import asyncio
import pytest

from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.ExchangeFactory import ExchangeFactory
from stock_data_downloader.models import HyperliquidExchangeConfig, ExchangeConfig

pytestmark = pytest.mark.skipif(
    not (os.getenv("HL_WALLET_ADDRESS") and os.getenv("HL_SECRET_KEY")) or os.getenv("ALLOW_TRADES") != "true",
    reason="Hyperliquid credentials or ALLOW_TRADES=true not set; skipping trade integration test",
)

@pytest.mark.asyncio
async def test_hyperliquid_place_and_cancel_small_order():
    exch_cfg = ExchangeConfig(exchange=HyperliquidExchangeConfig(
        type="hyperliquid",
        network=os.getenv("HYPERLIQUID_NETWORK", "testnet"),
        api_config={
            "wallet_address": os.getenv("HL_WALLET_ADDRESS"),
            "secret_key": os.getenv("HL_SECRET_KEY"),
        },
    ))
    portfolio = Portfolio(initial_cash=float(os.getenv("HL_TEST_INITIAL_CASH", "1000")))
    exchange = ExchangeFactory.create_exchange(exch_cfg, portfolio)

    symbol = os.getenv("HL_TEST_TICKER", "BTC")
    price = float(os.getenv("HL_TEST_PRICE", "100.0"))
    size = float(os.getenv("HL_TEST_SIZE", "0.001"))

    # place a tiny limit order then cancel
    results = await exchange.place_order([
        exchange.order_cls(
            symbol=symbol,
            side="buy",
            quantity=size,
            price=price,
            cloid="e2e-test",
            args={},
            timestamp=None,
        )
    ])
    assert results, "No result returned from place_order"

    # immediately cancel
    for r in results:
        if hasattr(r, "exchange_id"):
            await exchange.cancel_order(str(r.exchange_id))
