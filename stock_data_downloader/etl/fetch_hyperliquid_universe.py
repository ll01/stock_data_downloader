#!/usr/bin/env python3
"""Synchronize Hyperliquid perpetual universe metadata."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

BASE_URL = "https://api.hyperliquid.xyz/info"

logging.basicConfig(level=logging.INFO, format="%(message)s")


class FetchError(Exception):
    pass


def post_json(payload: dict[str, Any]) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{exc.code} {exc.reason}: {exc.read().decode(errors='ignore')}" ) from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Could not reach {BASE_URL}: {exc.reason}") from exc


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Hyperliquid perpetual universe metadata for backtesting."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/hyperliquid_universe.json"),
        help="Path to write the gathered universe data (default: config/hyperliquid_universe.json).",
    )
    parser.add_argument(
        "--include-asset-contexts",
        action="store_true",
        help="Also fetch the asset contexts alongside the universe (slower, more data).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence INFO logs and only show warnings/errors.",
    )
    return parser.parse_args()


def fetch_dex_list() -> list[str]:
    payload = post_json({"type": "perpDexs"})
    dex_names: list[str] = []
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict) and "name" in entry:
                dex_names.append(entry["name"])
            elif entry is None:
                dex_names.append("")
    return dex_names


def fetch_meta_for_dex(dex: str, include_contexts: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    entry["meta"] = post_json({"type": "meta", "dex": dex})
    if include_contexts:
        entry["contexts"] = post_json({"type": "metaAndAssetCtxs", "dex": dex})
    return entry


def main() -> None:
    args = parse_arguments()
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    try:
        dexes = fetch_dex_list()
    except FetchError as exc:
        logging.error("Failed to fetch perp dex list: %s", exc)
        sys.exit(1)
    if not dexes:
        logging.error("No dex entries were returned from Hyperliquid.")
        sys.exit(1)
    payload = {
        "fetched_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "dexes": {},
    }
    for dex in dexes:
        try:
            payload["dexes"][dex] = fetch_meta_for_dex(dex, args.include_asset_contexts)
        except FetchError as exc:
            logging.warning("Skipping %s because it could not be fetched: %s", dex, exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logging.info("Hyperliquid universe saved to %s", args.output)


if __name__ == "__main__":
    main()
