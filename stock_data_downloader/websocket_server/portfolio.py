import logging
from typing import Dict


logger = logging.getLogger(__name__)

class Portfolio:
    def __init__(self, initial_cash: float = 100000):
        self.cash = initial_cash
        self.positions = {}  # {ticker: (quantity, avg_price)}
        self.short_positions = {}  # {ticker: (quantity, entry_price)}
        self.trade_history = []

    def buy(self, ticker: str, quantity: int, price: float):
        cost = quantity * price
        if self.cash >= cost:
            self.cash -= cost
            if ticker in self.positions:
                old_qty, old_price = self.positions[ticker]
                new_qty = old_qty + quantity
                new_avg_price = (old_qty * old_price + quantity * price) / new_qty
                self.positions[ticker] = (new_qty, new_avg_price)
            else:
                self.positions[ticker] = (quantity, price)
            self.trade_history.append(("BUY", ticker, quantity, price, self.cash))
        else:
            logger.warning("Not enough cash to execute buy order")

    def short(self, ticker: str, quantity: int, price: float):
        # Short selling: sell first, buy back later
        self.cash += quantity * price  # Receive cash for selling borrowed shares
        if ticker in self.short_positions:
            old_qty, old_price = self.short_positions[ticker]
            new_qty = old_qty + quantity
            new_avg_price = (old_qty * old_price + quantity * price) / new_qty
            self.short_positions[ticker] = (new_qty, new_avg_price)
        else:
            self.short_positions[ticker] = (quantity, price)
        self.trade_history.append(("SHORT", ticker, quantity, price, self.cash))

    def sell(self, ticker: str, quantity: int, price: float):
        if ticker in self.positions and self.positions[ticker][0] >= quantity:
            self.cash += quantity * price
            new_qty = self.positions[ticker][0] - quantity
            if new_qty == 0:
                del self.positions[ticker]
            else:
                self.positions[ticker] = (new_qty, self.positions[ticker][1])
            self.trade_history.append(("SELL", ticker, quantity, price, self.cash))
        elif ticker in self.short_positions and self.short_positions[ticker][0] >= quantity:
            # Closing short position
            entry_price = self.short_positions[ticker][1]
            profit = (entry_price - price) * quantity
            self.cash += profit
            new_qty = self.short_positions[ticker][0] - quantity
            if new_qty == 0:
                del self.short_positions[ticker]
            else:
                self.short_positions[ticker] = (new_qty, entry_price)
            self.trade_history.append(("COVER", ticker, quantity, price, self.cash))
        else:
            logger.warning("Not enough shares to execute sell order")

    def value(self, prices: Dict[str, float]):
        long_value = sum(qty * prices[tick] for tick, (qty, _) in self.positions.items())
        short_value = sum(qty * (entry_price - prices[tick]) for tick, (qty, entry_price) in self.short_positions.items())
        return self.cash + long_value + short_value