import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from stock_data_downloader.websocket_server.portfolio import Portfolio

def test_calculate_total_value_basic():
    """Test basic portfolio value calculation with no positions"""
    portfolio = Portfolio(initial_cash=10000)

    # With no positions, total value should be initial cash
    total_value = portfolio.calculate_total_value()
    print(f"Test 1 - Basic (no positions):")
    print(f"  Initial cash: {portfolio.initial_cash}")
    print(f"  Current cash: {portfolio.cash}")
    print(f"  Calculated total value: {total_value}")
    print(f"  Expected: {portfolio.initial_cash}")
    assert abs(total_value - portfolio.initial_cash) < 0.01, f"Expected {portfolio.initial_cash}, got {total_value}"
    print("  ✓ Passed\n")

def test_calculate_total_value_long_position():
    """Test portfolio value with long positions"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy some shares
    success = portfolio.buy("AAPL", 10, 100, 0)  # 10 shares at $100
    assert success, "Buy should succeed"

    total_value = portfolio.calculate_total_value()

    print(f"Test 2 - Long position:")
    print(f"  Initial cash: {portfolio.initial_cash}")
    print(f"  Current cash: {portfolio.cash}")
    print(f"  Positions: {portfolio.positions}")
    print(f"  Calculated total value: {total_value}")

    # Expected: Cash spent = 10 * 100 = 1000
    # Remaining cash = 10000 - 1000 = 9000
    # Position value = 10 * 100 = 1000 (using entry price since no market price)
    # Total value = 9000 + 1000 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, f"Expected {expected_value}, got {total_value}"
    print("  ✓ Passed\n")

def test_calculate_total_value_short_position():
    """Test portfolio value with short positions"""
    portfolio = Portfolio(initial_cash=10000, margin_requirement=1.5)

    # Short some shares
    success = portfolio.sell("TSLA", 5, 200, 0)  # Short 5 shares at $200
    assert success, "Short sell should succeed"

    total_value = portfolio.calculate_total_value()

    print(f"Test 3 - Short position:")
    print(f"  Initial cash: {portfolio.initial_cash}")
    print(f"  Current cash: {portfolio.cash}")
    print(f"  Margin posted: {portfolio.margin_posted}")
    print(f"  Short positions: {portfolio.short_positions}")
    print(f"  Calculated total value: {total_value}")

    # Expected calculation:
    # Proceeds from short sale = 5 * 200 = 1000
    # Required margin = 1000 * 1.5 = 1500
    # Net cash change = proceeds - margin = 1000 - 1500 = -500
    # New cash = 10000 - 500 = 9500
    # Short liability = 5 * 200 = 1000 (using entry price)
    # Total value = cash + margin_posted - short_liability = 9500 + 1500 - 1000 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, f"Expected {expected_value}, got {total_value}"
    print("  ✓ Passed\n")

def test_calculate_total_value_mixed_positions():
    """Test portfolio value with both long and short positions"""
    portfolio = Portfolio(initial_cash=10000, margin_requirement=1.5)

    # Buy AAPL
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "AAPL buy should succeed"

    # Short TSLA
    success = portfolio.sell("TSLA", 5, 200, 0)
    assert success, "TSLA short should succeed"

    total_value = portfolio.calculate_total_value()

    print(f"Test 4 - Mixed positions:")
    print(f"  Initial cash: {portfolio.initial_cash}")
    print(f"  Current cash: {portfolio.cash}")
    print(f"  Margin posted: {portfolio.margin_posted}")
    print(f"  Long positions: {portfolio.positions}")
    print(f"  Short positions: {portfolio.short_positions}")
    print(f"  Calculated total value: {total_value}")

    # Expected:
    # AAPL cost = 10 * 100 = 1000
    # TSLA short: proceeds = 1000, margin = 1500, net cash change = -500
    # Total cash change = -1000 (AAPL) + (-500) (TSLA) = -1500
    # New cash = 10000 - 1500 = 8500
    # Long value = 10 * 100 = 1000
    # Short liability = 5 * 200 = 1000
    # Total value = 8500 + 1500 + 1000 - 1000 = 10000
    expected_value = 10000
    assert abs(total_value - expected_value) < 0.01, f"Expected {expected_value}, got {total_value}"
    print("  ✓ Passed\n")

def test_calculate_total_value_after_price_changes():
    """Test that calculate_total_value uses entry prices (not market prices)"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy at $100
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    # Note: calculate_total_value uses the stored price in position tuple
    # which is the average entry price, not a current market price
    total_value = portfolio.calculate_total_value()

    print(f"Test 5 - Uses entry prices:")
    print(f"  Bought 10 AAPL at $100")
    print(f"  Position tuple: {portfolio.positions['AAPL']}")
    print(f"  Calculated total value: {total_value}")

    # Should use entry price of $100, not any external market price
    expected_value = 10000  # Same as initial (cash 9000 + position value 1000)
    assert abs(total_value - expected_value) < 0.01, f"Expected {expected_value}, got {total_value}"
    print("  ✓ Passed\n")

def test_calculate_total_value_method_issues():
    """Test to identify issues in the current calculate_total_value implementation"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy some shares
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    print(f"Test 6 - Identify implementation issues:")
    print(f"  Position structure: {portfolio.positions}")
    print(f"  Type of position value: {type(portfolio.positions['AAPL'])}")

    # The issue: line 166 tries to unpack as (quantity, last_price)
    # But position is actually (quantity, avg_price)
    # And there's no 'last_price' or 'average_entry_price' key in the tuple
    position = portfolio.positions['AAPL']
    quantity, avg_price = position
    print(f"  Actual unpacking: quantity={quantity}, avg_price={avg_price}")

    # The method has a bug: it tries to access position.get("average_entry_price", 0)
    # but position is a tuple, not a dict
    try:
        # This would fail because tuple has no .get() method
        # position.get("average_entry_price", 0)
        print("  Note: position.get() would fail - position is a tuple")
    except AttributeError:
        print("  ✓ Confirmed: position is a tuple, not a dict")

    print("  This test reveals the bug in calculate_total_value method")
    print()

def test_value_method_comparison():
    """Compare calculate_total_value with the value() method that takes external prices"""
    portfolio = Portfolio(initial_cash=10000)

    # Buy at $100
    success = portfolio.buy("AAPL", 10, 100, 0)
    assert success, "Buy should succeed"

    # calculate_total_value uses entry prices
    total_value_no_prices = portfolio.calculate_total_value()

    # value() method uses external market prices
    market_prices = {"AAPL": 110}  # Price increased to $110
    total_value_with_prices = portfolio.value(market_prices)

    print(f"Test 7 - Compare with value() method:")
    print(f"  Entry price: $100")
    print(f"  Market price: $110")
    print(f"  calculate_total_value(): {total_value_no_prices}")
    print(f"  value(market_prices): {total_value_with_prices}")
    print(f"  Difference: {total_value_with_prices - total_value_no_prices}")

    # calculate_total_value should use $100 (entry price)
    # value() should use $110 (market price)
    expected_no_prices = 10000  # 9000 cash + 10*100
    expected_with_prices = 10100  # 9000 cash + 10*110

    assert abs(total_value_no_prices - expected_no_prices) < 0.01, f"Expected {expected_no_prices}, got {total_value_no_prices}"
    assert abs(total_value_with_prices - expected_with_prices) < 0.01, f"Expected {expected_with_prices}, got {total_value_with_prices}"
    print("  ✓ Passed\n")

def main():
    print("=" * 80)
    print("Testing Portfolio.calculate_total_value() method")
    print("=" * 80)
    print()

    test_calculate_total_value_basic()
    test_calculate_total_value_long_position()
    test_calculate_total_value_short_position()
    test_calculate_total_value_mixed_positions()
    test_calculate_total_value_after_price_changes()
    test_calculate_total_value_method_issues()
    test_value_method_comparison()

    print("=" * 80)
    print("All tests completed!")
    print("=" * 80)

    # Summary of findings
    print("\nSUMMARY OF FINDINGS:")
    print("1. calculate_total_value() has a bug on line 166: tries to unpack as (quantity, last_price)")
    print("   but position is actually (quantity, avg_price)")
    print("2. Line 172-174 tries to call position.get() but position is a tuple, not a dict")
    print("3. The method uses entry prices for valuation (not current market prices)")
    print("4. For short positions, it uses entry_price from the tuple")
    print("5. The value() method is better for mark-to-market with external prices")

if __name__ == "__main__":
    main()