---
# Stock Data Downloader

[![GitHub license](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)

The **Stock Data Downloader** is a Python application that fetches historical OHLC (Open, High, Low, Close) data for a list of stock tickers from a specified data provider (e.g., Yahoo Finance, Alpha Vantage). The data is cleaned, saved to CSV files, and zipped for easy distribution.

## Features

- **Fetch Historical Data**: Download OHLC data for multiple stock tickers concurrently.
- **Data Cleaning**: Handle outliers and interpolate missing values using robust methods.
- **Chunked Processing**: Process tickers in configurable chunks to manage API rate limits and system resources.
- **CSV and ZIP Output**: Save intermediate and final data to CSV files, and package them into a ZIP archive.
- **Customizable**: Configure date ranges, output paths, chunk sizes, data providers, and logging levels.
- **Logging**: Detailed logs for tracking progress and debugging.
- **Overwrite and Cleanup Options**: Flexible control over file management.

## Installation

### Prerequisites

- Python 3.11 or higher
- [Poetry](https://python-poetry.org/) for dependency management

### Steps

1. **Install Poetry** (if not already installed)
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/stock-data-downloader.git
   cd stock-data-downloader
   ```

3. **Install Dependencies**
   ```bash
   poetry install
   ```

## Usage

The `stock_data_downloader` project provides several entry points for different functionalities:

### 1. Downloading Historical Stock Data (`main.py`)

This script fetches historical OHLC data from a specified data provider.

```bash
poetry run python stock_data_downloader/main.py [OPTIONS]
```

**Options:**
- `--ticker-file <path>`: Path to the file containing tickers (default: `tickers.txt`).
- `--start-date <YYYY-MM-DD>`: Start date for the data (default: `2020-01-01`).
- `--end-date <YYYY-MM-DD>`: End date for the data (default: today).
- `--csv-file <path>`: Path to the output CSV file (default: `ohlc_data.csv`).
- `--zip-file <path>`: Path to the output ZIP file (default: `ohlc_data.zip`).
- `--data-provider <provider>`: Data provider to use (`yahoo` or `alphavantage`, default: `yahoo`).
- `--secret-file <path>`: Path to the file containing API keys/secrets (default: `secrets.json`).
- `--chunk-size <int>`: Number of tickers to process in each chunk (default: `10`).
- `--log-level <level>`: Set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, default: `INFO`).
- `--keep-csv`: Keep intermediate CSV files after zipping.

**Example:**
```bash
poetry run python stock_data_downloader/main.py --ticker-file my_tickers.txt --start-date 2023-01-01 --data-provider yahoo
```

### 2. Running Price Simulations (`sim.py`)

This script simulates stock prices using various models and can output the data to a Parquet file or stream it via a WebSocket.

```bash
poetry run python stock_data_downloader/sim.py [OPTIONS]
```

**Options:**
- `--sim_data_file <path>`: Path to the Parquet file containing ticker statistics (default: `data/sim_data.parquet`).
- `--output-format <format>`: Output format for results (`parquet` or `websocket`, default: `parquet`).
- `--output-file <path>`: Path to save simulated prices (if `output-format` is `parquet`, default: `simulated_prices.parquet`).
- `--websocket-uri <uri>`: WebSocket URI to send data (if `output-format` is `websocket`, default: finds a free port).
- `--time-steps <int>`: Number of timesteps to simulate (default: `100`).
- `--start-price <float>`: Starting price for all tickers (default: `100.0`).
- `--interval <float>`: Time interval between timesteps (default: `1.0`).
- `--realtime`: Whether to simulate realtime prices (default: `False`).
- `--seed <int>`: Random seed for reproducibility (default: `None`).
- `--log-level <level>`: Set the logging level (default: `INFO`).

**Examples:**
- **Save to Parquet:**
  ```bash
  poetry run python stock_data_downloader/sim.py --output-format parquet --sim_data_file data/sim_data.parquet --time-steps 252 --output-file simulated_heston_prices.parquet
  ```
- **Stream via WebSocket:**
  ```bash
  poetry run python stock_data_downloader/sim.py --output-format websocket --sim_data_file data/sim_data.parquet --time-steps 252 --websocket-uri ws://localhost:8765 --realtime
  ```

### 3. Running the WebSocket Server (`run_server.py`)

This script starts a WebSocket server that can serve either live data (via Hyperliquid) or simulated data (Brownian Motion, Heston Model) based on a `config.yml` file.

```bash
poetry run python stock_data_downloader/run_server.py --config <path_to_config.yml> [OPTIONS]
```

**Options:**
- `--config <path>`: **Required**. Path to the configuration file (JSON or YAML).
- `--log-level <level>`: Logging level (default: `INFO`).
- `--sim-data-file <path>`: Path to stock statistics data file (for Brownian/Heston simulation, overrides `data_source.stats` in config).
- `--start-price <float>`: Starting price for all assets in simulation mode (overrides `data_source.start_prices` in config).

**Example:**
```bash
poetry run python stock_data_downloader/run_server.py --config config.yml --sim-data-file data/sim_data.parquet
```

## Configuration (`config.yml`)

The `config.yml` file is central to configuring the WebSocket server's behavior, including its data source, exchange integration, and simulation parameters.

### General Structure

The `config.yml` is organized into several top-level sections:

- `simulation`: Controls global simulation settings.
- `exchange`: Configures the trading exchange interface.
- `data_source`: Defines the source of market data (live or simulated).
- `server`: Sets up WebSocket server parameters.
- `strategy`: (Optional) Configuration for trading strategies.

### Environment Variable Resolution

The configuration handler supports resolving environment variables within the `config.yml` using the `${VAR_NAME}` or `${VAR_NAME:-default_value}` syntax. This is particularly useful for sensitive information like API keys.

**Example:**
```yaml
secret_key: "${HYPERLIQUID_SECRET_KEY}"
```

### Section Details

#### `simulation`

This section controls global simulation settings.

- `enabled` (boolean): If `true`, the system operates in simulation mode. (Default: `false`).
- `initial_cash` (float): The starting cash balance for the portfolio in simulation mode. (Default: `1000.0`).

**Example:**
```yaml
simulation:
  enabled: true
  initial_cash: 100000.0
```

#### `exchange`

Configures the trading exchange interface.

- `type` (string): The type of exchange to use.
  - `test`: A mock exchange for testing and simulation (default).
  - `hyperliquid`: Integrates with the Hyperliquid exchange.
  - `cctx`: (If enabled) Integrates with exchanges supported by CCXT.

**`hyperliquid` specific settings:**
- `network` (string): `testnet` or `mainnet`.
- `config` (map):
  - `secret_key` (string): Your Hyperliquid private key (can be an environment variable).
  - `wallet_address` (string): Your Hyperliquid wallet address (can be an environment variable).

**`cctx` specific settings (if `CCTX_AVAILABLE`):**
- `config` (map): Standard CCXT exchange configuration (e.g., `api_key`, `api_secret`, `exchange_id`, `test_mode`).

**Example (`test` exchange):**
```yaml
exchange:
  type: test
```

**Example (`hyperliquid` exchange):**
```yaml
exchange:
  type: hyperliquid
  network: testnet
  config:
    secret_key: "${HYPERLIQUID_SECRET_KEY}"
    wallet_address: "${HYPERLIQUID_WALLET_ADDRESS}"
```

#### `data_source`

Defines the source of market data.

- `type` (string): The type of data source to use.
  - `brownian`: Simulates prices using Geometric Brownian Motion (GBM).
  - `heston`: Simulates prices using the Heston Model (stochastic volatility).
  - `hyperliquid`: Fetches live data from Hyperliquid.

**`brownian` (Geometric Brownian Motion) specific settings:**
- `timesteps` (int): Number of simulation steps.
- `interval` (float): Time interval between steps (e.g., `1.0` for daily).
- `wait_time` (float): Delay between sending price updates in real-time simulation.
- `seed` (int): Random seed for reproducibility.
- `stats` (map): (Optional) A map of ticker symbols to their `TickerStats` (mean, sd). If not provided, or if a ticker is missing, synthetic stats can be generated if `sim-data-file` is used with archetypes.
- `start_prices` (map): (Optional) A map of ticker symbols to their starting prices.

**`heston` (Heston Model) specific settings:**
- `timesteps` (int): Number of simulation steps.
- `interval` (float): Time interval between steps (`dt` for Heston, e.g., `0.003968` for daily steps, which is `1/252`).
- `wait_time` (float): Delay between sending price updates.
- `seed` (int): Random seed for reproducibility.
- `stats` (map): (Optional) A map of ticker symbols to their `TickerStats`, including Heston parameters (`kappa`, `theta`, `xi`, `rho`) and `degrees_of_freedom` for t-distribution.
- `start_prices` (map): (Optional) A map of ticker symbols to their starting prices.

**Simulating "Black Swan" Events with Heston Model:**
The `degrees_of_freedom` parameter in `TickerStats` (used with the `heston` data source) allows you to introduce "fat tails" to the price distribution, making extreme events more likely.
- A lower `degrees_of_freedom` (e.g., `3.0` to `5.0`) results in fatter tails and more frequent/larger extreme price movements.
- If `degrees_of_freedom` is `None` or not specified, a normal distribution is used for random shocks.

**`hyperliquid` specific settings:**
- `network` (string): `testnet` or `mainnet`.
- `tickers` (list of strings): List of ticker symbols to fetch data for.
- `api_config` (map): (Optional) API configuration for Hyperliquid data source if different from the exchange configuration.

**Example (`heston` data source with custom stats):**
```yaml
data_source:
  type: heston
  timesteps: 252
  interval: 0.003968
  wait_time: 0.1
  seed: 42
  stats:
    AAPL:
      mean: 0.0005
      sd: 0.01
      kappa: 3.0
      theta: 0.04
      xi: 0.3
      rho: -0.6
      degrees_of_freedom: 5.0 # Example: moderately fat tails
    GOOG:
      mean: 0.0008
      sd: 0.015
      kappa: 2.5
      theta: 0.05
      xi: 0.35
      rho: -0.65
      degrees_of_freedom: 3.0 # Example: very fat tails
  start_prices:
    AAPL: 150.0
    GOOG: 2000.0
```

#### `server`

Configures the WebSocket server itself.

- `uri` (string): The full WebSocket URI (e.g., `ws://localhost:8765`). If not specified, `host` and `port` are used.
- `host` (string): The host address to bind to (default: `localhost`).
- `port` (int): The port to listen on. If not specified, a free port is assigned.
- `max_in_flight_messages` (int): Maximum number of messages in the send queue before a client is considered slow.
- `ping_interval` (int): Interval (in seconds) for sending WebSocket pings (for live mode).
- `ping_timeout` (int): Timeout (in seconds) for WebSocket pings (for live mode).

**Example:**
```yaml
server:
  uri: ws://localhost:8765
  max_in_flight_messages: 10
  ping_interval: 20
  ping_timeout: 20
```

#### `strategy`

(Optional) Configuration for trading strategies. This section's content will vary depending on the specific strategy implemented.

**Example (`zscore` strategy):**
```yaml
strategy:
  type: zscore
  window_size: 20
  entry_threshold: 2
  exit_threshold: 1
  max_pairs: 10
  amount: 15
  filter_tickers: [] # e.g., ["BTC", "ETH"]
```

## Usage
[Rest of the content remains unchanged...]