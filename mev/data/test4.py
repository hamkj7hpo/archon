import asyncio
import websockets
import json
import requests

async def listen_for_logs():
    uri = "wss://api.mainnet-beta.solana.com"  # Solana WebSocket endpoint

    while True:  # Keep trying to reconnect in case of an error
        try:
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
                    # Send a ping to keep the connection alive
                    await ws.ping()

                    # Wait for a new log entry
                    response = await ws.recv()
                    log_data = json.loads(response)

                    # Print the entire response for debugging
                    print("Received log data:")
                    print(json.dumps(log_data, indent=2))

                    # Check if the response contains transaction data
                    if 'params' in log_data and 'result' in log_data['params']:
                        log_entry = log_data['params']['result']

                        # Print the log_entry to see its structure
                        print("Log entry details:")
                        print(json.dumps(log_entry, indent=2))

                        # Ensure that the signature field exists before accessing it
                        if 'signature' in log_entry:
                            transaction_signature = log_entry['signature']
                            print(f"New log received for transaction: {transaction_signature}")

                            # Fetch detailed transaction data using getTransaction() API
                            transaction_details = await fetch_transaction_details(transaction_signature)
                            if transaction_details:
                                print("Transaction details fetched successfully:")
                                print(transaction_details)

                                # Look for token transfer instructions and amounts
                                for instruction in transaction_details.get('transaction', {}).get('message', {}).get('instructions', []):
                                    if 'program' in instruction and instruction['program'] == 'spl-token':
                                        print(f"Token transfer instruction: {instruction}")
                                        # You can extract token transfer data here, e.g., from the `data` field
                                        # to get the amount of tokens transferred, sender, and receiver

        except websockets.exceptions.ConnectionClosedError as e:
            print(f"Connection closed with error: {e}. Reconnecting...")
            await asyncio.sleep(5)  # Wait before reconnecting

        except Exception as e:
            print(f"An error occurred: {e}")
            await asyncio.sleep(5)  # Wait before reconnecting

async def fetch_transaction_details(signature):
    # Solana RPC endpoint to fetch transaction details
    rpc_url = "https://api.mainnet-beta.solana.com"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "json"}]
    }

    response = requests.post(rpc_url, headers=headers, json=payload)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch transaction details: {response.status_code}")
        return None

# Run the asynchronous task
asyncio.get_event_loop().run_until_complete(listen_for_logs())
