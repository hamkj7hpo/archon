import asyncio
import websockets
import json

# Helius WebSocket endpoint with your API key
URI = "wss://mainnet.helius-rpc.com/?api-key=18e23183-7cc1-4373-8ccb-26ab8ea875ac"

# The market address from your output
MARKET_ADDRESS = "3RRsDyTQjA5gVeFgYBuMnsGgSQfz4No63tWzwCbffwVm"

async def test_websocket():
    print(f"Connecting to {URI}—LET’S 🤬 ROCK THIS!")
    try:
        async with websockets.connect(URI, ping_interval=20, ping_timeout=60) as ws:
            print("Connected—SENDING THE 🤬 SUBSCRIPTION!")
            # Subscription request
            sub_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "logsSubscribe",
                "params": [{"mentions": [MARKET_ADDRESS]}, {"commitment": "finalized"}]
            }
            await ws.send(json.dumps(sub_request))
            print(f"Sent subscription request for {MARKET_ADDRESS}—WAITING FOR THE 🤬 RESPONSE!")

            # Listen for the first few responses
            for _ in range(5):  # Grab 5 messages to see what’s up
                response = await ws.recv()
                data = json.loads(response)
                print("Received:", json.dumps(data, indent=2))
    except Exception as e:
        print(f"WebSocket error: {e}—SOMETHING’S 🤬 BUSTED!")

if __name__ == "__main__":
    asyncio.run(test_websocket())
