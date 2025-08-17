import pytest

from stock_data_downloader.websocket_server.DataSource.BacktestDataSource import BacktestDataSource


@pytest.mark.asyncio
async def test_get_historical_sets_historical_step_count_and_client_start():
    """
    Ensure get_historical_data sets _historical_step_count and that a client
    initialized after receiving full historical data will start at that offset.
    When the historical window covers the whole simulation, next_bar should
    signal end-of-simulation.
    """
    config = {
        "source_type": "backtest",
        "backtest_model_type": "gbm",
        "backtest_mode": "pull",
        "timesteps": 3,
        "interval": 1.0,
        "start_prices": {"AAA": 100.0, "BBB": 50.0},
        "ticker_configs": {
            "AAA": {"gbm": {"mean": 0.0, "sd": 0.1}},
            "BBB": {"gbm": {"mean": 0.0, "sd": 0.1}}
        }
    }

    ds = BacktestDataSource(backtest_config=config)
 
    # Request historical data (this should build the precomputed sequence)
    # Explicitly request the full historical window for this test so we can assert
    # the historical marker equals the configured timesteps (legacy behavior).
    hist = await ds.get_historical_data(history_steps=ds.backtest_config.timesteps)
    assert isinstance(hist, list)
    assert len(hist) > 0

    # historical_step_count should match configured timesteps
    assert ds._historical_step_count == ds.backtest_config.timesteps

    # New client asking for next bar when the entire simulation has already
    # been sent as historical should receive an end-of-simulation response.
    client_id = "client-1"
    resp = await ds.get_next_bar_for_client(client_id)

    # Either no data or an error_message indicating end-of-sim is acceptable
    assert (not resp.data) or (resp.error_message is not None)

    # Client pointer should be initialized to the historical offset
    assert ds.client_steps[client_id] == ds._historical_step_count


@pytest.mark.asyncio
async def test_client_offset_when_history_shorter_than_total():
    """
    Simulate the server having sent only the first N timesteps as history.
    Ensure get_next_bar_for_client begins at the historical offset and returns
    the precomputed timestep immediately following the history.
    """
    config = {
        "source_type": "backtest",
        "backtest_model_type": "gbm",
        "backtest_mode": "pull",
        "timesteps": 5,
        "interval": 1.0,
        "start_prices": {"AAA": 100.0, "BBB": 50.0},
        "ticker_configs": {
            "AAA": {"gbm": {"mean": 0.0, "sd": 0.1}},
            "BBB": {"gbm": {"mean": 0.0, "sd": 0.1}}
        }
    }

    ds = BacktestDataSource(backtest_config=config)

    # Build the precomputed sequence
    ds._ensure_precomputed()
    assert len(ds._precomputed) == 5

    # Simulate server sending only the first 3 timesteps as history
    ds._historical_step_count = 3

    client_id = "client-2"
    resp = await ds.get_next_bar_for_client(client_id)

    # Should return the timestep immediately after the history
    assert resp.error_message is None
    assert resp.data == ds._precomputed[3]

    # Client pointer should have advanced by one after returning the bar
    assert ds.client_steps[client_id] == 4