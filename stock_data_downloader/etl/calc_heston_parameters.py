#!/usr/bin/env python3
"""Estimate Heston parameters using free crypto price data from CoinGecko."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import logging
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Sequence


import statistics


COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
COINGECKO_MARKET_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"

# Known mappings help skip the coin list lookup for the most common tickers.
DEFAULT_TICKER_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "ADA": "cardano",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "DOGE": "dogecoin",
    "LTC": "litecoin",
    "XRP": "ripple",
    "FTM": "fantom",
    "SUI": "sui",
    "ARB": "arbitrum",
}

PRICE_SOURCES = ("coingecko", "livecoinwatch")
LIVECOINWATCH_HISTORY_URL = "https://api.livecoinwatch.com/coins/single/history"


logging.basicConfig(level=logging.INFO, format="%(message)s")


class FetchError(Exception):
    pass


def fetch_json(
    url: str,
    params: dict[str, str] | None = None,
    retries: int = 3,
    backoff_factor: float = 1.0,
) -> dict | list:
    query = urllib.parse.urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    logging.debug("Requesting %s", request_url)
    for i in range(retries):
        try:
            with urllib.request.urlopen(request_url, timeout=30) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError) as exc:
            if (
                isinstance(exc, urllib.error.HTTPError)
                and 400 <= exc.code < 500
                and exc.code != 429
            ):
                # Don't retry on client errors (e.g., 400 Bad Request), except for 429
                raise FetchError(
                    f"HTTP {exc.code} when requesting {request_url}: {exc.reason}"
                ) from exc

            if i < retries - 1:
                sleep_time = backoff_factor * (2**i)
                logging.warning(
                    "Request to %s failed with %s. Retrying in %.2f seconds...",
                    request_url,
                    exc,
                    sleep_time,
                )
                time.sleep(sleep_time)
            else:
                if isinstance(exc, urllib.error.HTTPError):
                    raise FetchError(
                        f"Failed to fetch {request_url} after {retries} attempts. Last error: HTTP {exc.code} {exc.reason}"
                    ) from exc
                else:
                    raise FetchError(
                        f"Failed to fetch {request_url} after {retries} attempts. Last error: {exc}"
                    ) from exc


def post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    retries: int = 3,
    backoff_factor: float = 1.0,
) -> dict | list:
    logging.debug("Requesting %s with payload %s", url, payload)
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    for i in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError) as exc:
            if (
                isinstance(exc, urllib.error.HTTPError)
                and 400 <= exc.code < 500
                and exc.code != 429
            ):
                # Don't retry on client errors (e.g., 400 Bad Request), except for 429
                raise FetchError(
                    f"HTTP {exc.code} when requesting {url}: {exc.reason}"
                ) from exc

            if i < retries - 1:
                sleep_time = backoff_factor * (2**i)
                logging.warning(
                    "Request to %s failed with %s. Retrying in %.2f seconds...",
                    url,
                    exc,
                    sleep_time,
                )
                time.sleep(sleep_time)
            else:
                if isinstance(exc, urllib.error.HTTPError):
                    raise FetchError(
                        f"Failed to fetch {url} after {retries} attempts. Last error: HTTP {exc.code} {exc.reason}"
                    ) from exc
                else:
                    raise FetchError(
                        f"Failed to fetch {url} after {retries} attempts. Last error: {exc}"
                    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pulls historical crypto prices from CoinGecko or LiveCoinWatch and "
            "estimates Heston parameters for each ticker."
        )
    )
    parser.add_argument(
        "--hyperliquid-universe",
        type=str,
        help="Path to a JSON file containing Hyperliquid universe metadata. If provided, tickers will be derived from this file.",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default="BTC,ETH,SOL",
        help="Comma-separated tickers to fetch. Defaults to BTC,ETH,SOL.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of history to consider per ticker.",
    )
    parser.add_argument(
        "--interval-days",
        type=float,
        default=1.0,
        help="Time step in days (dt) used when calibrating the Heston model.",
    )
    parser.add_argument(
        "--vs-currency",
        type=str,
        default="usd",
        help="Quote currency for the market data.",
    )
    parser.add_argument(
        "--price-source",
        type=str.lower,
        choices=PRICE_SOURCES,
        default="livecoinwatch",
        help="Price data provider (coingecko or livecoinwatch).",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        help="Optional path to persist the calculated parameters as CSV.",
    )
    parser.add_argument(
        "--livecoinwatch-api-key",
        type=str,
        help="LiveCoinWatch API key when --price-source=livecoinwatch.",
    )
    parser.add_argument(
        "--coingecko-id",
        action="append",
        default=[],
        help="Override mapping for a ticker (format TICKER=gecko-id); can be repeated.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.2,
        help="Seconds to wait between CoinGecko requests (default: 1.2).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable informational logging and only print results.",
    )
    return parser.parse_args()


def parse_tickers(value: str) -> list[str]:
    tokens = [token.strip().upper() for token in value.split(",") if token.strip()]
    if not tokens:
        raise ValueError("Please provide at least one ticker to analyze.")
    return tokens


def parse_overrides(values: Sequence[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError("--coingecko-id overrides must use the form TICKER=coingecko-id")
        ticker, coin_id = raw.split("=", 1)
        overrides[ticker.strip().upper()] = coin_id.strip()
    return overrides


def fetch_coin_list() -> list[dict[str, str]]:
    logging.info("Fetching CoinGecko coin list to resolve tickers...")
    payload = fetch_json(COINGECKO_LIST_URL)
    if not isinstance(payload, list):
        raise FetchError("CoinGecko /coins/list returned unexpected payload")
    return payload


def resolve_coin_id(
    ticker: str, overrides: dict[str, str], coin_list: list[dict[str, str]]
) -> str | None:
    ticker = ticker.upper()
    if ticker in overrides:
        return overrides[ticker]
    if ticker in DEFAULT_TICKER_IDS:
        return DEFAULT_TICKER_IDS[ticker]
    symbol = ticker.lower()
    for coin in coin_list:
        if coin.get("symbol", "").lower() == symbol:
            return coin.get("id")
    return None


def fetch_price_history(
    coin_id: str, vs_currency: str, days: int
) -> list[float]:
    target = COINGECKO_MARKET_URL.format(coin_id=coin_id)
    params = {"vs_currency": vs_currency, "days": str(days)}
    payload = fetch_json(target, params)
    if not isinstance(payload, dict):
        raise FetchError("Unexpected response for market chart data")
    raw_prices = payload.get("prices", [])
    prices = []
    for point in raw_prices:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            prices.append(float(point[1]))
    return prices


def fetch_price_history_livecoinwatch(
    ticker: str, vs_currency: str, days: int, api_key: str
) -> list[float]:
    if not api_key:
        raise FetchError("LiveCoinWatch API key is required to fetch price history")
    end_ts = int(time.time() * 1000)
    start_ts = end_ts - int(days * 86400 * 1000)
    payload = {
        "currency": vs_currency.upper(),
        "code": ticker.upper(),
        "start": start_ts,
        "end": end_ts,
        "meta": False,
    }
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    response = post_json(LIVECOINWATCH_HISTORY_URL, payload, headers)
    if not isinstance(response, dict):
        raise FetchError("Unexpected response from LiveCoinWatch history")
    history = response.get("history", [])
    if not isinstance(history, list):
        raise FetchError("LiveCoinWatch history payload missing 'history'")
    prices: list[float] = []
    for entry in history:
        rate = entry.get("rate")
        if rate is None:
            continue
        try:
            prices.append(float(rate))
        except (TypeError, ValueError):
            continue
    if not prices:
        raise FetchError(f"LiveCoinWatch did not return any price points for {ticker}")
    return prices


def compute_log_returns(prices: list[float]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0 or current <= 0:
            continue
        returns.append(math.log(current / previous))
    return returns


def compute_autocorrelation(series: Iterable[float]) -> float:
    values = list(series)
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    numerator = 0.0
    denominator = 0.0
    for i in range(1, len(values)):
        numerator += (values[i] - mean) * (values[i - 1] - mean)
    for value in values:
        denominator += (value - mean) ** 2
    if denominator == 0:
        return 0.0
    normalized = (numerator / (len(values) - 1)) / (denominator / len(values))
    return max(min(normalized, 0.999), -0.999)


def compute_correlation(xs: Iterable[float], ys: Iterable[float]) -> float:
    x_values = list(xs)
    y_values = list(ys)
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return 0.0
    mean_x = statistics.mean(x_values)
    mean_y = statistics.mean(y_values)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    var_x = sum((x - mean_x) ** 2 for x in x_values)
    var_y = sum((y - mean_y) ** 2 for y in y_values)
    if var_x == 0 or var_y == 0:
        return 0.0
    return max(min(cov / math.sqrt(var_x * var_y), 0.99), -0.99)


def estimate_heston_parameters(returns: list[float], dt: float) -> dict[str, float]:
    if not returns:
        return {"kappa": 1.0, "theta": 0.04, "xi": 0.3, "rho": -0.5}
    raw_theta = statistics.pvariance(returns)
    theta = max(raw_theta, 1e-8)
    squared = [value * value for value in returns]
    raw_autocorr = compute_autocorrelation(squared)
    if raw_autocorr <= 0:
        kappa = 1.0
    else:
        kappa = -math.log(min(raw_autocorr, 0.999)) / max(dt, 1e-6)
    kappa = min(max(kappa, 0.2), 5.0)
    variance_of_squared = statistics.pvariance(squared)
    xi = math.sqrt(max(variance_of_squared, 1e-10) / theta)
    xi = min(max(xi, 0.1), 1.5)
    rho = compute_correlation(returns[1:], squared[:-1])
    rho = max(min(rho, 0.95), -0.95)
    return {"kappa": kappa, "theta": theta, "xi": xi, "rho": rho}


def write_csv(path: str, rows: list[dict[str, str | float]]) -> None:
    fieldnames = [
        "ticker",
        "coin_id",
        "observations",
        "mean_return",
        "volatility",
        "kappa",
        "theta",
        "xi",
        "rho",
        "interval_days",
        "start_price",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    logging.info("Parameters saved to %s", path)


def main() -> None:
    args = parse_args()
    if args.price_source == "livecoinwatch" and not args.livecoinwatch_api_key:
        logging.error("--livecoinwatch-api-key is required when --price-source=livecoinwatch")
        sys.exit(1)
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    try:
        if args.hyperliquid_universe:
            with open(args.hyperliquid_universe, "r") as universe_metadata_file:
                universe_metadata = json.loads(universe_metadata_file.read())
                # the blank dex name is the default tickers for hyperliquid
                tickers = [str(market["name"]) for market in universe_metadata["dexes"][""]["meta"]["universe"]]
        else:
            tickers = parse_tickers(args.tickers)
    except ValueError as exc:
        logging.error("%s", exc)
        sys.exit(1)
    overrides = parse_overrides(args.coingecko_id)
    coin_list: list[dict[str, str]] = []
    if args.price_source == "coingecko":
        if overrides or any(ticker not in DEFAULT_TICKER_IDS for ticker in tickers):
            try:
                coin_list = fetch_coin_list()
            except FetchError as exc:
                logging.error("Failed to download coin list: %s", exc)
                sys.exit(1)
    rows: list[dict[str, str | float]] = []
    for ticker in tickers:
        coin_id = ticker
        if args.price_source == "coingecko":
            coin_id = resolve_coin_id(ticker, overrides, coin_list)
            if not coin_id:
                logging.warning("Unable to resolve CoinGecko id for %s", ticker)
                continue
            fetcher = fetch_price_history
            fetch_args = (coin_id, args.vs_currency, args.days)
        else:
            fetcher = fetch_price_history_livecoinwatch
            fetch_args = (
                ticker,
                args.vs_currency,
                args.days,
                args.livecoinwatch_api_key,
            )
        try:
            prices = fetcher(*fetch_args)
        except FetchError as exc:
            logging.warning("Skipping %s because price fetch failed: %s", ticker, exc)
            continue
        if len(prices) < 5:
            logging.warning("Not enough prices for %s (only %d points)", ticker, len(prices))
            continue
        returns = compute_log_returns(prices)
        params = estimate_heston_parameters(returns, args.interval_days)
        mean_return = statistics.mean(returns) if returns else 0.0
        volatility = math.sqrt(statistics.pvariance(returns)) if returns else 0.0
        logging.info(
            "%s: kappa=%.3f theta=%.5f xi=%.3f rho=%.3f (mean=%.5f vol=%.5f)",
            ticker,
            params["kappa"],
            params["theta"],
            params["xi"],
            params["rho"],
            mean_return,
            volatility,
        )
        # Use the last price from the history as the start price
        start_price = prices[-1] if prices else 100.0
        rows.append(
            {
                "ticker": ticker,
                "coin_id": coin_id,
                "observations": len(returns),
                "mean_return": mean_return,
                "volatility": volatility,
                "kappa": params["kappa"],
                "theta": params["theta"],
                "xi": params["xi"],
                "rho": params["rho"],
                "interval_days": args.interval_days,
                "start_price": start_price,
            }
        )
        time.sleep(args.sleep)
    if args.output_csv and rows:
        save_path = args.output_csv
    else:
        now = time.strftime("%Y%m%d-%H%M%S")
        file_name = f"heston_parameters_days_{args.days}_{now}.csv"
        save_path = os.path.join("./", "config", file_name)
    write_csv(save_path, rows)


if __name__ == "__main__":
    main()
