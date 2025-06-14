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

### Quick Example

Run the downloader with default settings:
```bash
poetry run python main.py --ticker-file tickers.txt
```

## Usage
[Rest of the content remains unchanged...]