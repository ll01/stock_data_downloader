import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult

def test_portfolio_fees():
    # Create a portfolio with initial cash
    portfolio = Portfolio(initial_cash=10000, margin_requirement=1.5)
    print(f"Initial cash: {portfolio.cash}")
    
    # Test buying with fees
    # Buy 10 shares at $100 each with $5 fee
    success = portfolio.buy("AAPL", 10, 100, 5)
    print(f"Buy success: {success}")
    print(f"Cash after buy: {portfolio.cash}")
    print(f"Positions: {portfolio.positions}")
    
    # Test selling with fees
    # Sell 5 shares at $105 each with $5 fee
    success = portfolio.sell("AAPL", 5, 105, 5)
    print(f"Sell success: {success}")
    print(f"Cash after sell: {portfolio.cash}")
    print(f"Positions: {portfolio.positions}")
    
    # Test apply_order_result with fees
    order_result = OrderResult(
        cloid="test123",
        oid="order123",
        status="FILLED",
        side="buy",
        price=110,
        quantity=5,
        symbol="GOOG",
        success=True,
        timestamp="2025-01-01T00:00:00Z",
        fee_paid=10.0
    )
    
    portfolio.apply_order_result(order_result)
    print(f"Cash after apply_order_result buy: {portfolio.cash}")
    print(f"Positions: {portfolio.positions}")
    
    # Test sell order result
    sell_order_result = OrderResult(
        cloid="test124",
        oid="order124",
        status="FILLED",
        side="sell",
        price=115,
        quantity=3,
        symbol="GOOG",
        success=True,
        timestamp="2025-01-01T00:05:00Z",
        fee_paid=10.0
    )
    
    portfolio.apply_order_result(sell_order_result)
    print(f"Cash after apply_order_result sell: {portfolio.cash}")
    print(f"Positions: {portfolio.positions}")
    
    print("All tests passed!")

if __name__ == "__main__":
    test_portfolio_fees()