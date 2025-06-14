from typing import List
from stock_data_downloader.websocket_server.DataSource.DataSourceInterface import DataSourceInterface
from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import ExchangeInterface
from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.OrderResult import OrderResult
from stock_data_downloader.websocket_server.portfolio import Portfolio

class TradingSystem:
    def __init__(self, exchange: ExchangeInterface, portfolio: Portfolio, data_source: DataSourceInterface):
        self.exchange = exchange
        self.portfolio = portfolio
        self.data_source = data_source
