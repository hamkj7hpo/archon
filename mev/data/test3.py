import asyncio
import websockets
import json

async def listen_for_logs():
    uri = "wss://api.mainnet-beta.solana.com"  # Solana WebSocket endpoint
    async with websockets.connect(uri) as ws:
        print("Successfully connected to Solana WebSocket!")

        # The address you want to monitor
        address_to_monitor = "BjZKz1z4UMjJPvPfKwTwjPErVBWnewnJFvcZB6minymy"

        # Send a request to subscribe to logs for the specific address
        request = {
            "jsonrpc": "2.0",
            "method": "logsSubscribe",  # subscribe to logs
            "params": [{
                "mentions": [address_to_monitor]  # Monitor logs for this address
            }],
            "id": 1
        }

        await ws.send(json.dumps(request))
        print(f"Subscribed to logs for address: {address_to_monitor}")

        while True:
            response = await ws.recv()
            print("New log update received:")
            print(response)

# Run the asynchronous task
asyncio.get_event_loop().run_until_complete(listen_for_logs())
