import logging
from typing import Dict, Any

from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import ExchangeInterface
from stock_data_downloader.websocket_server.ExchangeInterface.HyperliquidExchange import HyperliquidExchange
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import TestExchange
from stock_data_downloader.websocket_server.portfolio import Portfolio

# Import CCTXExchange if available
try:
    from stock_data_downloader.websocket_server.ExchangeInterface.CCTXExchange import CCTXExchange
    CCTX_AVAILABLE = True
except ImportError:
    CCTX_AVAILABLE = False
    CCTXExchange = None
    logging.warning("CCTXExchange not found. CCTX exchange will not be available.")

logger = logging.getLogger(__name__)

class ExchangeFactory:
    """Factory class for creating exchange instances based on configuration"""
    
    @staticmethod
    def create_exchange(config: Dict[str, Any], portfolio: Portfolio) -> ExchangeInterface:
        """
        Create an exchange instance based on the provided configuration
        
        Args:
            config: Dictionary with exchange configuration
            portfolio: Portfolio instance to use with the exchange
            
        Returns:
            ExchangeInterface implementation
        
        Raises:
            ValueError: If the exchange type is not supported
        """
        exchange_type = config.get("type", "test").lower()
        
        # Extract general exchange settings
        simulation_mode = config.get("simulation_mode", True)
        
        if exchange_type == "test":
            logger.info("Creating TestExchange")
            return TestExchange(
                portfolio=portfolio,
                simulation_mode=simulation_mode
            )
        
        elif exchange_type == "hyperliquid":
            logger.info("Creating HyperliquidExchange")
            network = config.get("network", "testnet")
            exchange_config = config.get("config", {})
            return HyperliquidExchange(
                config=exchange_config,
                network=network
            )
        
        elif exchange_type == "cctx" and CCTX_AVAILABLE:
            logger.info("Creating CCTXExchange")
            exchange_config = config.get("config", {})
            assert CCTXExchange is not None, "CCTXExchange is not enabled."
            return CCTXExchange(
                config=exchange_config
            )
        
        else:
            available_types = ["test", "hyperliquid"]
            if CCTX_AVAILABLE:
                available_types.append("cctx")
                
            err_msg = f"Exchange type '{exchange_type}' not supported. Available types: {', '.join(available_types)}"
            logger.error(err_msg)
            raise ValueError(err_msg)


