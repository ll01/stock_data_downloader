from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.factories.ExchangeFactory import ExchangeFactory
from stock_data_downloader.models import AppConfig

class SimulationSession:
    """
    Encapsulates all the state for a single, isolated backtest simulation.
    """
    def __init__(self, client_id: str, app_config: AppConfig):
        self.client_id = client_id
        self.portfolio = Portfolio(initial_cash=app_config.initial_cash, margin_requirement=1.5)
        # Use the factory to create a new exchange instance for this session
        self.exchange = ExchangeFactory.create_exchange(app_config.exchange, self.portfolio)
