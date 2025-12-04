import asyncio
import uuid
from datetime import datetime, timezone

from stock_data_downloader.websocket_server.ExchangeInterface.Order import Order
from stock_data_downloader.websocket_server.ExchangeInterface.HyperliquidExchange import HyperliquidExchange
from stock_data_downloader.models import HyperliquidExchangeConfig


async def main():
    # ——————— CONFIG ———————
    # Fill in your own testnet private key here:
    config = HyperliquidExchangeConfig(
        type="hyperliquid",
        api_config={
            "secret_key": "your_testnet_private_key_here",
            "wallet_address": "your_wallet_address_here",
        },
        network="testnet"
    )

    # Instantiate on testnet
    exchange = HyperliquidExchange(config=config)

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
    if results:
        res = results[0]
        print(f"[{datetime.utcnow().isoformat()}] OrderResult:")
        print(res)

        # ——————— CANCEL THE ORDER ———————
        # We cancel using whichever ID the mapping stored (prefers cloid over oid)
        cancel_id = res.cloid or res.oid
        if cancel_id:
            print(f"[{datetime.utcnow().isoformat()}] Cancelling order {cancel_id}…")
            cancelled = await exchange.cancel_order(cancel_id)
            print(f"[{datetime.utcnow().isoformat()}] Cancel successful? {cancelled}")
        else:
            print("No valid order ID to cancel")
    else:
        print("No results returned from place_order")

    # ——————— DONE ———————
    await exchange.unsubscribe_to_orders([])  # clean up any subscriptions
    print("All done.")


if __name__ == "__main__":
    asyncio.run(main())