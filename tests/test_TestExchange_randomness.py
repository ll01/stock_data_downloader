import asyncio
import pytest
import statistics
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import TestExchange
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order

@pytest.mark.asyncio
async def test_fixed_slippage():
    """Verify that fixed slippage is deterministic"""
    portfolio = Portfolio(initial_cash=10000)
    exchange = TestExchange(
        portfolio=portfolio,
        slippage_bps=50.0, # 0.5%
        slippage_model="fixed"
    )
    
    order = Order(
        symbol="TEST",
        side="buy",
        quantity=1.0,
        price=100.0,
        args={},
        timestamp="2023-01-01T00:00:00Z"
    )
    
    results = await exchange.place_order([order])
    assert results[0].success
    # Expected price: 100 * (1 + 0.005) = 100.5
    # Fees are applied ON TOP of slippage-adjusted price.
    # But place_order returns the 'price' field as adjusted_price BEFORE fee calculation for the result object?
    # Let's check implementation:
    # adjusted_price = order.price * (1 + slippage_factor)
    # result.price = adjusted_price
    # Fee: 100.5 * (1 + 0.0005) = 100.55025
    assert results[0].price == pytest.approx(100.55025)

@pytest.mark.asyncio
async def test_randomized_slippage():
    """Verify that randomized slippage produces variable results"""
    portfolio = Portfolio(initial_cash=1000000)
    exchange = TestExchange(
        portfolio=portfolio,
        slippage_bps=50.0, # Mean 0.5%
        slippage_model="normal",
        slippage_variability_bps=10.0 # StdDev 0.1%
    )
    
    prices = []
    for _ in range(100):
        order = Order(
            symbol="TEST",
            side="buy",
            quantity=1.0,
            price=100.0,
            args={},
            timestamp="2023-01-01T00:00:00Z"
        )
        results = await exchange.place_order([order])
        prices.append(results[0].price)
        
    # Check that we have some variability
    stdev = statistics.stdev(prices)
    mean = statistics.mean(prices)
    
    # Variability should be non-zero
    assert stdev > 0
    
    # Mean should be close to 100.5 (within standard error)
    assert mean == pytest.approx(100.5, rel=0.01)
    
    # Prices should not be all identical
    assert len(set(prices)) > 50 
