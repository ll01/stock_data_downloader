import argparse
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
from functools import partial
from math import exp
from multiprocessing import Pool
from typing import Dict, List, Optional
import pandas as pd
from stock_data_downloader.config.logging_config import setup_logging
from stock_data_downloader.config.sim_arg_parser import parse_arguments
from stock_data_downloader.data_processing.simulation import run_simulation, simulate_prices
import websockets
import socket


# Load mean and standard deviation from a Parquet file
def load_stats_from_parquet(parquet_file: str, ticker: str) -> tuple[float, float]:
    """
    Load mean and standard deviation for a specific ticker from a Parquet file.
    """
    try:
        df = pd.read_parquet(parquet_file)
        stats = df[df["ticker"] == ticker].iloc[0]
        return stats["mean"], stats["sd"]
    except Exception as e:
        logging.error(f"Error loading stats from Parquet file: {e}")
        raise


# Send simulated prices to a WebSocket
async def send_to_websocket(uri: str, prices: Dict[str, List[float]]):
    """
    Send simulated prices for multiple tickers to a WebSocket server.
    """

    max_lengh = max([len(prices) for prices in prices.values()])
    now = datetime.now()
    async with websockets.connect(uri) as websocket:
        for i in range(max_lengh):
            for ticker in prices.keys():
                current_price = prices[ticker][i] if i < len(prices[ticker]) else None
                current_time = (now + timedelta(days=1)).isoformat()
                if current_price is not None:
                    data = {
                        "timestamp": current_time,
                        "ticker": ticker,
                        "price": current_price,
                    }
                    await websocket.send(json.dumps(data))


def find_free_port():
    """Finds a free port on the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))  # Bind to any available port
        return s.getsockname()[1]


def save_to_parquet(
    simulated_prices: Dict[str, List[Dict[str, float]]], output_file: str
):
    """Saves the simulated prices to a Parquet file."""
    try:
        dfs = []
        for ticker, ohlc_data in simulated_prices.items():
            ticker_df = pd.DataFrame(ohlc_data)
            ticker_df["ticker"] = ticker
            dfs.append(ticker_df)
        final_df = pd.concat(dfs, ignore_index=True)
        final_df.to_parquet(output_file)
        logging.info(f"Simulated data saved to {output_file}")
    except Exception as e:
        logging.exception(f"Error saving to Parquet: {e}")


async def handle_websocket_output(
    simulated_prices: Dict[str, List[Dict[str, float]]], websocket_uri: Optional[str]
):
    """Handles sending simulated prices to a WebSocket."""
    if websocket_uri:
        uri = websocket_uri
    else:
        port = find_free_port()
        uri = f"ws://localhost:{port}"
        logging.info(f"Starting WebSocket server on {uri}")

        async def websocket_server(websocket, path):
            await send_to_websocket(uri, simulated_prices)
            try:
                while True:
                    await asyncio.sleep(1)
            except websockets.exceptions.ConnectionClosedOK:
                pass

        async with websockets.serve(websocket_server, "localhost", port):
            await asyncio.Future()  # run forever

    await send_to_websocket(uri, simulated_prices)


async def main():
    args = parse_arguments()
    setup_logging(args.log_level)

    simulated_prices = await run_simulation(args)

    if simulated_prices:  # Check if simulation was successful
        if args.output_format == "parquet":
            save_to_parquet(simulated_prices, args.output_file)
        elif args.output_format == "websocket":
            await handle_websocket_output(simulated_prices, args.websocket_uri)


if __name__ == "__main__":
    asyncio.run(main())
