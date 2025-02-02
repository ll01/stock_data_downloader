# Stock Data Downloader

The **Stock Data Downloader** is a Python application that fetches historical OHLC (Open, High, Low, Close) data for a list of stock tickers from a specified data provider (e.g., Yahoo Finance, Alpha Vantage). The data is cleaned, saved to CSV files, and zipped for easy distribution.

## Features

- **Fetch Historical Data**: Download OHLC data for multiple stock tickers.
- **Data Cleaning**: Handle outliers and interpolate missing values.
- **Chunked Processing**: Process tickers in chunks to avoid overwhelming the data provider.
- **CSV and ZIP Output**: Save cleaned data to CSV files and zip them for convenience.
- **Customizable**: Supports multiple data providers (e.g., Yahoo Finance, Alpha Vantage) and allows customization of date ranges, output files, chunk sizes, and more.
- **Logging**: Configurable logging levels for better debugging and tracking.
- **Overwrite and Cleanup Options**: Control whether to overwrite existing files or keep intermediate CSV files.

## Installation

### Prerequisites

- Python 3.8 or higher
- `pip` for installing dependencies

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/stock-data-downloader.git
   cd stock-data-downloader
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `tickers.txt` file in the root directory and add the stock tickers you want to download, one per line. For example:
   ```
   AAPL
   MSFT
   GOOG
   ```

4. (Optional) If using Alpha Vantage or another provider requiring API keys, create a `secrets.json` file with the required credentials. For example:
   ```json
   {
     "alphavantage": "your_api_key_here"
   }
   ```

## Usage

Run the script with the following command:

```bash
python main.py --ticker-file tickers.txt --start-date 2020-01-01 --end-date 2023-10-01 --csv-file ohlc_data.csv --zip-file ohlc_data.zip --data-provider yahoo
```

### Command-Line Arguments

| Argument            | Description                                                                 | Default Value         |
|---------------------|-----------------------------------------------------------------------------|-----------------------|
| `--ticker-file`     | Path to the file containing stock tickers.                                  | `tickers.txt`         |
| `--start-date`      | Start date for the data in `YYYY-MM-DD` format.                             | `2020-01-01`          |
| `--end-date`        | End date for the data in `YYYY-MM-DD` format.                               | Today's date          |
| `--csv-file`        | Path to the output CSV file.                                                | `ohlc_data.csv`       |
| `--zip-file`        | Path to the output ZIP file.                                                | `ohlc_data.zip`       |
| `--data-provider`   | Data provider to use (`yahoo` or `alphavantage`).                           | `yahoo`               |
| `--secret-file`     | Path to the file containing API keys or secrets.                            | `secrets.json`        |
| `--chunk-size`      | Number of tickers to process in each chunk.                                 | `10`                  |
| `--log-level`       | Set the logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).    | `INFO`                |
| `--overwrite`       | Overwrite existing CSV and ZIP files if they exist.                         | `False`               |
| `--keep-csv`        | Keep intermediate CSV files after zipping.                                  | `False`               |

### Example Commands

1. **Basic Usage**:
   Download data for the tickers listed in `tickers.txt` from January 1, 2020, to October 1, 2023, and save the cleaned data to `ohlc_data.csv` and `ohlc_data.zip`:
   ```bash
   python main.py --ticker-file tickers.txt --start-date 2020-01-01 --end-date 2023-10-01 --csv-file ohlc_data.csv --zip-file ohlc_data.zip --data-provider yahoo
   ```

2. **Custom Chunk Size and Log Level**:
   Process 20 tickers at a time and set the logging level to `DEBUG`:
   ```bash
   python main.py --ticker-file tickers.txt --chunk-size 20 --log-level DEBUG
   ```

3. **Overwrite Existing Files**:
   Overwrite existing CSV and ZIP files:
   ```bash
   python main.py --ticker-file tickers.txt --overwrite
   ```

4. **Keep Intermediate CSV Files**:
   Keep intermediate CSV files after zipping:
   ```bash
   python main.py --ticker-file tickers.txt --keep-csv
   ```

5. **Use Alpha Vantage with API Key**:
   Use Alpha Vantage as the data provider and specify the API key file:
   ```bash
   python main.py --ticker-file tickers.txt --data-provider alphavantage --secret-file my_secrets.json
   ```

## Output

- **CSV Files**: Cleaned OHLC data is saved in chunks (e.g., `ohlc_data_part0.csv`, `ohlc_data_part1.csv`).
- **ZIP File**: All CSV files are zipped into a single file (e.g., `ohlc_data.zip`).
- **Logs**: Logs are saved to `app.log` for debugging and tracking.

## Data Cleaning

The application uses an `OutlierIdentifier` to detect and handle outliers in the data. Outliers are identified using the Interquartile Range (IQR) method and interpolated using linear interpolation.

## Supported Data Providers

- **Yahoo Finance**: Default provider for fetching historical stock data.
- **Alpha Vantage**: Requires an API key (provided in `secrets.json`).

## Contributing

Contributions are welcome! If you'd like to contribute, please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature or bugfix.
3. Commit your changes and push to the branch.
4. Submit a pull request.