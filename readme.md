# Stock Data Downloader - Testing & Backtest Pull-Mode

This document outlines how to run core tests, use the new backtest pull-mode for multi-instance simulations, and (optionally) run Hyperliquid integration tests. It also notes Windows-specific asyncio behavior and safety considerations for exchange testing.

## Backtest (Pull Mode) Overview
- BacktestDataSource now supports a pull-driven model suitable for multi-instance backtesting.
- In pull mode, clients request the next bar explicitly (action: "next_bar").
- The server assigns a per-connection `client_id` and replies with `price_update` messages per client. When the simulation is exhausted, a `simulation_end` message is returned.
- Pull mode is enabled by default for BacktestDataSource. Live sources remain push-based.

### Message examples
- Welcome (server->client): `{ "type": "welcome", "data": { "client_id": "<uuid>", "mode": "pull" } }`
- Request next bar (client->server): `{ "action": "next_bar" }`
- Price update (server->client): `{ "type": "price_update", "data": [ {ticker, timestamp, open, high, low, close, volume}, ... ] }`
- End (server->client): `{ "type": "simulation_end", "data": {} }`

## Deterministic Simulators
- GBMSimulator and HestonSimulator use per-instance RNGs for deterministic behavior: same seed => same sequence.

## Running Core Tests
From the `stock_data_downloader` directory:

- Core deterministic simulation test and per-client backtest integration test:

```
pytest -q tests/data_processing/simulation_test.py tests/test_per_client_backtest.py
```

Notes:
- The per-client test starts a websocket server on localhost and verifies two clients can step independently to the end of the simulation.
- Server supports a `stop_event` for clean shutdown during tests.
- On Windows, you may still see some asyncio teardown warnings; these are benign for tests.

## Hyperliquid Integration Tests (Optional)
These are skipped by default unless the required environment variables are set.

### Data Source Subscribe Test
Validates that HyperliquidDataSource can connect and receive at least one tick.

Requirements (environment variables):
- `HL_WALLET_ADDRESS`
- `HL_SECRET_KEY`
- Optional: `HYPERLIQUID_NETWORK` (default `testnet`), `HL_TEST_TICKER` (default `BTC`)

Run:
```
pytest -q tests/hyperliquid/test_datasource_integration.py
```

### Exchange Place/Cancel Test (E2E - Testnet Only)
Places a tiny limit order and cancels it immediately on Hyperliquid testnet.

Additional requirements:
- Set `ALLOW_TRADES=true` to enable this test (otherwise skipped)
- Optional:
  - `HL_TEST_INITIAL_CASH` (default `1000`)
  - `HL_TEST_TICKER` (default `BTC`)
  - `HL_TEST_PRICE` (default `100.0`)
  - `HL_TEST_SIZE` (default `0.001`)

Run:
```
pytest -q tests/hyperliquid/test_exchange_integration.py
```

Safety:
- Tests will not run unless `ALLOW_TRADES=true` is set.
- Only runs on `testnet` by default and uses very small order sizes.
- Never print or commit secrets.

## Windows Notes
- You may observe occasional "Task was destroyed but it is pending!" or "Event loop is closed" during teardown under Windows. The code handles graceful shutdown where possible; these warnings are harmless in tests. If desired, set pytest-asyncio loop scope explicitly in `pytest.ini` to reduce differences:

```
[pytest]
asyncio_default_fixture_loop_scope=function
```

## Troubleshooting
- If you see `trade_rejection` for `next_bar`, ensure your data source is in pull mode (BacktestDataSource defaults to pull). For live sources, `next_bar` is not supported.
- If tests hang, verify no firewall is blocking localhost websocket connections and no other process is using the chosen port.
