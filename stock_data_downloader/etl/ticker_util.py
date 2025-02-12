def load_tickers_from_file(file_path):
    """Load tickers from a file."""
    with open(file_path, "r") as file:
        tickers = [line.strip() for line in file if line.strip()]
    return tickers