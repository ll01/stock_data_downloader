import pytest
from unittest.mock import MagicMock
from stock_data_downloader.websocket_server.MessageHandler import MessageHandler
from stock_data_downloader.websocket_server.portfolio import Portfolio
from stock_data_downloader.websocket_server.ExchangeInterface.TestExchange import (
    TestExchange,
)
from stock_data_downloader.websocket_server.trading_system import TradingSystem


@pytest.fixture
def message_handler():
    return MessageHandler()


@pytest.fixture
def test_trading_system():
    portfolio = Portfolio(initial_cash=10_000)
    exchange = TestExchange(portfolio)
    return TradingSystem(
        exchange=exchange,
        portfolio=portfolio,
        data_source=MagicMock(),
    )


@pytest.mark.asyncio
async def test_valid_buy_order(message_handler, test_trading_system):
    message = {
        "action": "order",
        "payload": {
            "ticker": "AAPL",
            "quantity": 10,
            "price": 150.0,
            "order_type": "buy",
        },
    }
    result = await message_handler.handle_message(
        message,
        trading_system=test_trading_system,
        simulation_running=False,
        realtime=False
    )
    assert result.result_type == "order_confirmation"


@pytest.mark.asyncio
async def test_valid_sell_order(message_handler, test_trading_system):
    message = {
        "action": "order",
        "payload": {
            "ticker": "AAPL",
            "quantity": 5,
            "price": 150.0,
            "order_type": "sell",
        },
    }
    result = await message_handler.handle_message(
        message,
        trading_system=test_trading_system,
        simulation_running=False,
        realtime=False
    )
    assert result.result_type == "order_confirmation"


@pytest.mark.asyncio
async def test_invalid_action(message_handler, test_trading_system):
    message = {
        "action": "invalid_action",
        "payload": {"ticker": "AAPL", "quantity": 10, "price": 150.0},
    }
    result = await message_handler.handle_message(
        message,
        trading_system=test_trading_system,
        simulation_running=False,
        realtime=False
    )
    assert result.result_type == "trade_rejection"


@pytest.mark.asyncio
async def test_reset_action(message_handler, test_trading_system):
    message = {"action": "reset"}
    result = await message_handler.handle_message(
        message,
        trading_system=test_trading_system,
        simulation_running=False,
        realtime=False
    )
    assert result.result_type == "reset_requested"


@pytest.mark.asyncio
async def test_missing_ticker(message_handler, test_trading_system):
    message = {
        "action": "order",
        "payload": {"quantity": 10, "price": 150.0, "order_type": "buy"},
    }
    result = await message_handler.handle_message(
        message,
        trading_system=test_trading_system,
        simulation_running=False,
        realtime=False
    )
    assert result.result_type == "trade_rejection"
    assert "ticker" in result.payload.get("reason", "").lower()


@pytest.mark.asyncio
async def test_zero_quantity(message_handler, test_trading_system):
    message = {
        "action": "order",
        "payload": {
            "ticker": "AAPL",
            "quantity": 0,
            "price": 150.0,
            "order_type": "buy",
        },
    }
    result = await message_handler.handle_message(
        message,
        trading_system=test_trading_system,
        simulation_running=False,
        realtime=False
    )
    assert result.result_type == "trade_rejection"
    assert "quantity" in result.payload.get("reason", "").lower()