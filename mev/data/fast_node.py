import asyncio
import websockets
import json

# Serum Market Address (Example: SOL/USDC)
market_address = "Cqt1J8ET5rxEiHEAjRGGBjgbceouMs4uDnnE634xnmK3"  # Change for your market

async def listen_trades():
    uri = "wss://mainnet.helius-rpc.com/?api-key=18e23183-7cc1-4373-8ccb-26ab8ea875ac"  # Replace with a premium WebSocket provider

    async with websockets.connect(uri) as ws:
        # Subscribe to Serum trade events
        sub_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [market_address]},
                {"commitment": "finalized"}
            ]
        }
        
        await ws.send(json.dumps(sub_request))

        while True:
            response = await ws.recv()
            trade_data = json.loads(response)
            print(trade_data)  # Process real-time trade feed

asyncio.run(listen_trades())
