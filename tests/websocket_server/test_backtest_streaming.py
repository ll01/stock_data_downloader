# import pytest
# from unittest.mock import AsyncMock, MagicMock
# from datetime import datetime, timedelta, timezone
# import asyncio

# from common.models import HestonConfig, GBMConfig, TickerConfig, TickerData
# from stock_data_downloader.websocket_server.factories.DataSourceFactory import DataSourceFactory
# from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource
# # from stock_data_downloader.data_processing.simulation import generate_heston_ticks, generate_gbm_ticks

# @pytest.fixture
# def heston_config_data():
#     return {
#         "type": "backtest",
#         "model_type": "heston",
#         "stats": {
#             "BTC": {"kappa": 3.0, "theta": 0.04, "xi": 0.3, "rho": -0.6},
#             "ETH": {"kappa": 2.5, "theta": 0.03, "xi": 0.25, "rho": -0.5}
#         },
#         "start_prices": {"BTC": 30000.0, "ETH": 2000.0},
#         "timesteps": 10,
#         "interval": 1.0/252,
#         "seed": 42
#     }

# @pytest.fixture
# def gbm_config_data():
#     return {
#         "type": "backtest",
#         "model_type": "gbm",
#         "stats": {
#             "AAPL": {"mean": 0.0005, "sd": 0.01},
#             "GOOG": {"mean": 0.0006, "sd": 0.012}
#         },
#         "start_prices": {"AAPL": 150.0, "GOOG": 100.0},
#         "timesteps": 10,
#         "interval": 1.0/252,
#         "seed": 42
#     }

# @pytest.mark.asyncio
# async def test_factory_conversion_heston(heston_config_data):
#     data_source = DataSourceFactory.create_data_source(heston_config_data)
#     assert isinstance(data_source, BacktestDataSource)
#     assert "BTC" in data_source.ticker_configs
#     assert isinstance(data_source.ticker_configs["BTC"], TickerConfig)
#     assert isinstance(data_source.ticker_configs["BTC"].heston, HestonConfig)
#     assert data_source.ticker_configs["BTC"].heston.kappa == 3.0

# @pytest.mark.asyncio
# async def test_factory_conversion_gbm(gbm_config_data):
#     data_source = DataSourceFactory.create_data_source(gbm_config_data)
#     assert isinstance(data_source, BacktestDataSource)
#     assert "AAPL" in data_source.ticker_configs
#     assert isinstance(data_source.ticker_configs["AAPL"], TickerConfig)
#     assert isinstance(data_source.ticker_configs["AAPL"].gbm, GBMConfig)
#     assert data_source.ticker_configs["AAPL"].gbm.mean == 0.0005

# @pytest.mark.asyncio
# async def test_backtest_data_source_heston_streaming(heston_config_data):
#     data_source = BacktestDataSource(DataSourceFactory.create_data_source(heston_config_data).ticker_configs, heston_config_data)
#     mock_callback = AsyncMock()
#     await data_source.subscribe_realtime_data(mock_callback)

#     # Expecting timesteps * number of tickers calls
#     expected_calls = heston_config_data["timesteps"] * len(heston_config_data["stats"])
#     assert mock_callback.call_count == expected_calls

#     # Verify the structure of the data received by the callback
#     for call_args in mock_callback.call_args_list:
#         event_type, data = call_args.args
#         assert event_type == "price_update"
#         assert isinstance(data, dict) # It's a dict because of model_dump()
#         assert "ticker" in data
#         assert "close" in data
#         assert "timestamp" in data
#         assert "volume" in data

# # @pytest.mark.asyncio
# # async def test_backtest_data_source_gbm_streaming(gbm_config_data):
# #     data_source = BacktestDataSource(DataSourceFactory.create_data_source(gbm_config_data).ticker_configs, gbm_config_data)
# #     mock_callback = AsyncMock()
# #     await data_source.subscribe_realtime_data(mock_callback)

# #     # Expecting timesteps * number of tickers calls
# #     expected_calls = gbm_config_data["timesteps"] * len(gbm_config_data["stats"])
# #     assert mock_callback.call_count == expected_calls

# #     # Verify the structure of the data received by the callback
# #     for call_args in mock_callback.call_args_list:
# #         event_type, data = call_args.args
# #         assert event_type == "price_update"
# #         assert isinstance(data, dict) # It's a dict because of model_dump()
# #         assert "ticker" in data
# #         assert "close" in data
# #         assert "timestamp" in data
# #         assert "volume" in data

# @pytest.mark.asyncio
# async def test_heston_generator_output_type(heston_config_data):
#     ticker_configs = {}
#     for ticker, params in heston_config_data['stats'].items():
#         ticker_configs[ticker] = TickerConfig(heston=HestonConfig(**params))

#     generator = generate_heston_ticks(
#         stats=ticker_configs,
#         start_prices=heston_config_data['start_prices'],
#         timesteps=heston_config_data['timesteps'],
#         dt=heston_config_data['interval'],
#         seed=heston_config_data['seed']
#     )
    
#     count = 0
#     async for tick_data in generator:
#         assert isinstance(tick_data, TickerData)
#         assert isinstance(tick_data.ticker, str)
#         assert isinstance(tick_data.price, float)
#         assert isinstance(tick_data.timestamp, float)
#         assert isinstance(tick_data.volume, float)
#         count += 1
#     assert count == heston_config_data["timesteps"] * len(heston_config_data["stats"])

# @pytest.mark.asyncio
# async def test_gbm_generator_output_type(gbm_config_data):
#     ticker_configs = {}
#     for ticker, params in gbm_config_data['stats'].items():
#         ticker_configs[ticker] = TickerConfig(gbm=GBMConfig(**params))

#     generator = generate_gbm_ticks(
#         stats=ticker_configs,
#         start_prices=gbm_config_data['start_prices'],
#         timesteps=gbm_config_data['timesteps'],
#         dt=gbm_config_data['interval'],
#         seed=gbm_config_data['seed']
#     )
    
#     count = 0
#     async for tick_data in generator:
#         assert isinstance(tick_data, TickerData)
#         assert isinstance(tick_data.ticker, str)
#         assert isinstance(tick_data.price, float)
#         assert isinstance(tick_data.timestamp, float)
#         assert isinstance(tick_data.volume, float)
#         count += 1
#     assert count == gbm_config_data["timesteps"] * len(gbm_config_data["stats"])


