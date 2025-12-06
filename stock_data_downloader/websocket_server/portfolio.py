import logging
from typing import Dict

from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult


logger = logging.getLogger(__name__)


class Portfolio:
    def __init__(self, initial_cash: float = 100000):
        self.cash = initial_cash
        self.positions = {}  # {ticker: (quantity, avg_price)}
        self.short_positions = {}  # {ticker: (quantity, entry_price)}
        self.trade_history = []
        self.initial_cash = initial_cash
    
    def clear_positions(self):
        """Clear all positions and short positions"""
        self.cash = self.initial_cash
        self.positions = {}
        self.short_positions = {}
        self.trade_history = []
    
    def buy(self, ticker: str, quantity: float, price: float, fee: float = 0.0) -> bool:
        cost = quantity * price
        total_cost = cost + fee  # Include fees in total cost
        success = False

        if self.cash >= total_cost:
            if (
                ticker in self.short_positions
                and self.short_positions[ticker][0] >= quantity
            ):
                # Cover Short Position
                success = True
                entry_price = self.short_positions[ticker][1]
                profit = (entry_price - price) * quantity
                self.cash += profit - fee  # Deduct fee from profit
                new_qty = self.short_positions[ticker][0] - quantity
                if new_qty == 0:
                    del self.short_positions[ticker]
                else:
                    self.short_positions[ticker] = (new_qty, entry_price)
                self.trade_history.append(("COVER", ticker, quantity, price, self.cash))
            else:
                # Open Long Position
                success = True
                self.cash -= total_cost  # Deduct total cost including fees
                if ticker in self.positions:
                    old_qty, old_price = self.positions[ticker]
                    new_qty = old_qty + quantity
                    # Calculate new average price including fees
                    new_avg_price = (old_qty * old_price + quantity * price + fee) / new_qty
                    self.positions[ticker] = (new_qty, new_avg_price)
                else:
                    # Include fees in the average price calculation
                    avg_price_with_fees = (quantity * price + fee) / quantity
                    self.positions[ticker] = (quantity, avg_price_with_fees)
                self.trade_history.append(("BUY", ticker, quantity, price, self.cash))
        else:
            logger.warning("Not enough cash to execute buy order")
        return success

    def sell(self, ticker: str, quantity: float, price: float, fee: float = 0.0) -> bool:
        success = False
        if ticker in self.positions and self.positions[ticker][0] >= quantity:
            # Sell Long Position
            success = True
            proceeds = quantity * price
            self.cash += proceeds - fee  # Deduct fees from proceeds
            new_qty = self.positions[ticker][0] - quantity
            if new_qty == 0:
                del self.positions[ticker]
            else:
                self.positions[ticker] = (new_qty, self.positions[ticker][1])
            self.trade_history.append(("SELL", ticker, quantity, price, self.cash))
        else:
            # Open/Increase Short Position
            # First check if we have any long position to sell
            if ticker in self.positions:
                current_position = self.positions[ticker][0]
                diff = quantity - current_position
                if diff > 0:
                    # First sell existing long position
                    success = self.sell(ticker, current_position, price, fee * (current_position / quantity) if quantity > 0 else 0)
                    # Then open new short position for remaining quantity
                    quantity = diff
                    if quantity <= 0:
                        return success
                    # Adjust fee for remaining short position
                    fee = fee * (quantity / (quantity + current_position)) if (quantity + current_position) > 0 else fee
                else:
                    # Just sell part of existing long position
                    return self.sell(ticker, quantity, price, fee)

            success = True
            proceeds = quantity * price
            self.cash += proceeds - fee  # Deduct fees from proceeds
            if ticker in self.short_positions:
                old_qty, old_price = self.short_positions[ticker]
                new_qty = old_qty + quantity
                # Calculate new average price including fees
                new_avg_price = (old_qty * old_price + quantity * price + fee) / new_qty
                self.short_positions[ticker] = (new_qty, new_avg_price)
            else:
                # Include fees in the average price calculation
                avg_price_with_fees = (quantity * price + fee) / quantity
                self.short_positions[ticker] = (quantity, avg_price_with_fees)
            self.trade_history.append(("SHORT", ticker, quantity, price, self.cash))
        return success

    def value(self, prices: Dict[str, float]) -> float:
        long_value = sum(
            qty * prices[tick] for tick, (qty, _) in self.positions.items()
        )
        # Calculate liability for short positions
        short_liability = sum(
            qty * prices[tick]
            for tick, (qty, entry_price) in self.short_positions.items()
        )
        # Equity = Cash + Long Value - Short Liability
        return self.cash + long_value - short_liability

    def calculate_total_value(self):
        market_value_long = 0
        market_value_short_liability = 0

        for ticker, position in self.positions.items():
            quantity, last_price = position

            if last_price is None:
                logger.warning(
                    f"Cannot mark-to-market {ticker}, final price unknown. Using average entry price."
                )
                last_price = position.get(
                    "average_entry_price", 0
                )  # Portfolio needs to track this

            if quantity > 0:
                market_value_long += quantity * last_price
        
        for ticker, position in self.short_positions.items():
            quantity, entry_price = position
            # For shorts, we need the current price to calculate liability.
            # But here we only have entry_price stored in the tuple if we don't have external prices.
            # This method seems to rely on the tuple having (qty, price).
            # In positions: (qty, avg_price).
            # In short_positions: (qty, entry_price).
            # If we interpret entry_price as "last known price" (which is wrong but all we have),
            # then liability is qty * entry_price.
            market_value_short_liability += quantity * entry_price

        return self.cash + market_value_long - market_value_short_liability

    def calculate_total_return(self) -> float:
        final_value = self.calculate_total_value()
        return (
            (final_value - self.initial_cash) / self.initial_cash
            if self.initial_cash
            else 0
        )

    def apply_order_result(self, result: OrderResult):
        if result.side == "buy":
            self.buy(result.symbol, result.quantity, result.price, result.fee_paid)
        elif result.side == "sell":
            self.sell(result.symbol, result.quantity, result.price, result.fee_paid)

        
