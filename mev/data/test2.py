import asyncio
import websockets
from solana.rpc.async_api import AsyncClient
from solana.publickey import PublicKey
from solana.rpc.types import TokenAccountOpts

# Solana WebSocket URL
WEB_SOCKET_URL = "wss://api.mainnet-beta.solana.com"

# The public key of the account or program you want to track
public_key = PublicKey('DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263')

# Create a WebSocket connection and listen for updates
async def listen_to_account_changes():
    async with websockets.connect(WEB_SOCKET_URL) as ws:
        # Subscribe to account changes (replace with your public key)
        subscription_request = {
            "jsonrpc": "2.0",
            "method": "accountSubscribe",
            "params": [str(public_key)],
            "id": 1
        }

        # Send subscription request
        await ws.send(str(subscription_request))
        print(f"Listening for account changes for {public_key}...")

        while True:
            # Listen for messages from the WebSocket connection
            message = await ws.recv()
            print(f"Received: {message}")

# Run the listener
asyncio.get_event_loop().run_until_complete(listen_to_account_changes())
