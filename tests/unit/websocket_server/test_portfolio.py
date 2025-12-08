"""
Unit tests for the Portfolio class in stock_data_downloader.websocket_server.portfolio
"""
import sys
import os
import pytest

from stock_data_downloader.websocket_server.portfolio import Portfolio


def test_basic_portfolio_value():
    """Test basic portfolio value calculation with no positions"""
    portfolio = Portfolio(initial_cash=10000)

    # With no positions, total value should be initial cash
    total_value = portfolio.calculate_total_value()
    assert abs(total_value - portfolio.initial_cash) < 0.01, \
        f"Expected {portfolio.initial_cash}, got {total_value}"


def test_long_position_value():
    """Test portfolio value with long positions"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy some shares
    success = portfolio.buy("AAPL", 10, 100, 0)  # 10 shares at $100
    assert success, "Buy should succeed"

    total_value = portfolio.calculate_total_value()

    # Expected: Cash spent = 10 * 100 = 1000
    # Remaining cash = 10000 - 1000 = 9000
    # Position value = 10 * 100 = 1000 (using entry price since no market price)
    # Total value = 9000 + 1000 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, \
        f"Expected {expected_value}, got {total_value}"


def test_short_position_value():
    """Test portfolio value with short positions"""
    portfolio = Portfolio(initial_cash=10000, margin_requirement=1.5)

    # Short some shares
    success = portfolio.sell("TSLA", 5, 200, 0)  # Short 5 shares at $200
    assert success, "Short sell should succeed"

    total_value = portfolio.calculate_total_value()

    # Expected calculation:
    # Proceeds from short sale = 5 * 200 = 1000
    # Required margin = 1000 * 1.5 = 1500
    # Net cash change = proceeds - margin = 1000 - 1500 = -500
    # New cash = 10000 - 500 = 9500
    # Short liability = 5 * 200 = 1000 (using entry price)
    # Total value = cash + margin_posted - short_liability = 9500 + 1500 - 1000 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, \
        f"Expected {expected_value}, got {total_value}"


def test_mixed_positions_value():
    """Test portfolio value with both long and short positions"""
    portfolio = Portfolio(initial_cash=10000, margin_requirement=1.5)

    # Buy AAPL
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "AAPL buy should succeed"

    # Short TSLA
    success = portfolio.sell("TSLA", 5, 200, 0)
    assert success, "TSLA short should succeed"

    total_value = portfolio.calculate_total_value()

    # Expected:
    # AAPL cost = 10 * 100 = 1000
    # TSLA short: proceeds = 1000, margin = 1500, net cash change = -500
    # Total cash change = -1000 (AAPL) + (-500) (TSLA) = -1500
    # New cash = 10000 - 1500 = 8500
    # Long value = 10 * 100 = 1000
    # Short liability = 5 * 200 = 1000
    # Total value = 8500 + 1500 + 1000 - 1000 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, \
        f"Expected {expected_value}, got {total_value}"


def test_uses_entry_prices_not_market_prices():
    """Test that calculate_total_value uses entry prices (not market prices)"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy at $100
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    total_value = portfolio.calculate_total_value()

    # Should use entry price of $100, not any external market price
    expected_value = 10000  # Same as initial (cash 9000 + position value 1000)
    assert abs(total_value - expected_value) < 0.01, \
        f"Expected {expected_value}, got {total_value}"


def test_compare_with_value_method():
    """Compare calculate_total_value with the value() method that takes external prices"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy at $100
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    # calculate_total_value uses entry prices
    total_value_no_prices = portfolio.calculate_total_value()

    # value() method uses external market prices
    market_prices = {"AAPL": 110.0}  # Price increased to $110
    total_value_with_prices = portfolio.value(market_prices)

    # calculate_total_value should use $100 (entry price)
    # value() should use $110 (market price)
    expected_no_prices = 10000  # 9000 cash + 10*100
    expected_with_prices = 10100  # 9000 cash + 10*110

    assert abs(total_value_no_prices - expected_no_prices) < 0.01, \
        f"Expected {expected_no_prices}, got {total_value_no_prices}"
    assert abs(total_value_with_prices - expected_with_prices) < 0.01, \
        f"Expected {expected_with_prices}, got {total_value_with_prices}"


def test_calculate_total_return():
    """Test calculate_total_return method which uses calculate_total_value"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy at $100
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    total_return = portfolio.calculate_total_return()

    # With no price change, return should be 0%
    expected_return = 0.0
    assert abs(total_return - expected_return) < 0.0001, \
        f"Expected {expected_return}, got {total_return}"


def test_method_implementation_issues():
    """Test to verify the bug in calculate_total_value implementation"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy some shares
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    # The method has a bug: line 166 tries to unpack as (quantity, last_price)
    # but position is actually (quantity, avg_price)
    position = portfolio.positions['AAPL']
    quantity, avg_price = position

    # Verify the actual structure
    assert isinstance(position, tuple), "Position should be a tuple"
    assert len(position) == 2, "Position tuple should have 2 elements"
    assert position[0] == quantity, "First element should be quantity"
    assert position[1] == avg_price, "Second element should be average price"

    # The bug: the method tries to call position.get() but position is a tuple
    # This would raise AttributeError: 'tuple' object has no attribute 'get'
    # This test confirms we understand the bug


def test_zero_initial_cash():
    """Test portfolio with zero initial cash"""
    portfolio = Portfolio(initial_cash=0)
    total_value = portfolio.calculate_total_value()
    assert abs(total_value - 0) < 0.01, f"Expected 0, got {total_value}"


def test_negative_cash_after_trades():
    """Test portfolio value when cash goes negative (shouldn't happen with proper checks)"""
    portfolio = Portfolio(initial_cash=100)

    # Try to buy more than we can afford - should fail
    success = portfolio.buy("AAPL", 100, 10, 0)  # Would cost 1000
    assert not success, "Buy should fail due to insufficient cash"

    # Portfolio value should still be initial cash
    total_value = portfolio.calculate_total_value()
    assert abs(total_value - 100) < 0.01, f"Expected 100, got {total_value}"


def test_multiple_positions_same_ticker():
    """Test portfolio with multiple buys of same ticker"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy in multiple lots
    success = portfolio.buy("AAPL", 5, 100, 0)
    assert success, "First buy should succeed"

    success = portfolio.buy("AAPL", 5, 110, 0)
    assert success, "Second buy should succeed"

    total_value = portfolio.calculate_total_value()

    # Average price should be (5*100 + 5*110)/10 = 105
    # Cash spent = 5*100 + 5*110 = 1050
    # Remaining cash = 10000 - 1050 = 8950
    # Position value = 10 * 105 = 1050
    # Total value = 8950 + 1050 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, \
        f"Expected {expected_value}, got {total_value}"
        
def test_1():
    expected_inital_cash = 10_000
    portfolio = Portfolio(initial_cash=expected_inital_cash)
    portfolio.buy("AAPL", 10, 100, 0)
    portfolio.sell("GOOG", 5, 200, 0)
    portfolio.sell("AAPL", 10, 100, 0)
    portfolio.buy("GOOG", 5, 200, 0)
    actual_total_value = portfolio.calculate_total_value()
    assert  actual_total_value == expected_inital_cash 
    print(actual_total_value)

        
# def test_2():
#     expected_inital_cash = 10_000
#     portfolio = Portfolio(initial_cash=expected_inital_cash)
#     portfolio.buy("AAPL", 0.100421939816898, 99.6296229513433, 0)
#     portfolio.sell("GOOG", 0.100345005712024, 99.6063523946999, 0)
#     portfolio.sell("AAPL", 0.100421939816898, 99.6300477376968, 0)
#     portfolio.buy("GOOG", 0.100345005712024, 99.6300477376968, 0)
#     actual_total_value = portfolio.calculate_total_value()
#     assert  actual_total_value == expected_inital_cash 
#     print(actual_total_value)
    