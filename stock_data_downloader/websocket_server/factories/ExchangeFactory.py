import logging
from typing import Dict, Any

from stock_data_downloader.models import AppConfig, ExchangeConfig
from stock_data_downloader.websocket_server.ExchangeInterface.CCTXExchange import CCTXExchange
from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import ExchangeInterface
from stock_data_downloader.websocket_server.ExchangeInterface.HyperliquidExchange import HyperliquidExchange
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import TestExchange
from stock_data_downloader.websocket_server.portfolio import Portfolio

logger = logging.getLogger(__name__)

class ExchangeFactory:
    @staticmethod
    def create_exchange(cfg: ExchangeConfig, portfolio: Portfolio):
        ex_cfg = cfg.exchange
        match ex_cfg.type:
            case "test":
                return TestExchange(portfolio=portfolio)
            case "hyperliquid":
                return HyperliquidExchange(ex_cfg)
            case "ccxt":
                return CCTXExchange(ex_cfg)
        raise ValueError(f"Unknown exchange type {ex_cfg.type}")

