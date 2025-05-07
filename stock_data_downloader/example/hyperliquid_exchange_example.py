import asyncio
import uuid
from datetime import datetime, timezone
from typing import List


from stock_data_downloader.websocket_server.ExchangeInterface.ExchangeInterface import Order
from stock_data_downloader.websocket_server.ExchangeInterface.HyperliquidExchange import HyperliquidExchange

async def main():
    # ——————— CONFIG ———————
    # Fill in your own testnet private key here:
    config = {
        "secret_key": "your_testnet_private_key_here",
        # you can also toggle this if you want to skip the extra status fetch:
        "fetch_status_after_order": True,
    }

    # Instantiate on testnet
    exchange = HyperliquidExchange(config=config, network="testnet")

    # ——————— PLACE A “RESTING” BUY ORDER ———————
    # We'll buy $12 worth of ETH at price $1 (so it never executes on testnet).
    # CLOID is just a UUID so we can trace it in our mapping.
    cloid = "0x"+ uuid.uuid4().hex
    order = Order(
        cloid=cloid,
        symbol="ETH",
        side="buy",
        quantity=12.0,    # $12 notional size
        price=1420,        # far below market
        args={},           # no extra args
        timestamp=datetime.now(timezone.utc).isoformat()
    )

    print(f"[{datetime.utcnow().isoformat()}] Placing order cloid={cloid}…")
    results = await exchange.place_order([order])

    # Should only be one result
    res = results[0]
    print(f"[{datetime.utcnow().isoformat()}] OrderResult:")
    print(res)

    # ——————— CANCEL THE ORDER ———————
    # We cancel using whichever ID the mapping stored (prefers cloid over oid)
    cancel_id = res.cloid or res.oid
    print(f"[{datetime.utcnow().isoformat()}] Cancelling order {cancel_id}…")
    cancelled = await exchange.cancel_order(cancel_id)
    print(f"[{datetime.utcnow().isoformat()}] Cancel successful? {cancelled}")

    # ——————— DONE ———————
    await exchange.unsubscribe_to_orders([])  # clean up any subscriptions
    print("All done.")

if __name__ == "__main__":
    asyncio.run(main())