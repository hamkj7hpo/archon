import asyncio
import websockets
import json
import os
import time
import sys

# Market Address (e.g., SOL/USDC)
market_address = "Cqt1J8ET5rxEiHEAjRGGBjgbceouMs4uDnnE634xnmK3"

# Output paths
input_file = "./json_data/transactions/yzy_loop.json"
output_directory = "./json_data/trades/yzy_trade_loop/"

async def fetch_transaction_details(transaction_hash, trade_data, output_dir):
    """Save transaction details from WebSocket to a file."""
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{transaction_hash}.json")
    
    with open(output_file, 'w') as json_file:
        json.dump(trade_data, json_file, indent=4)
    
    print(f"Transaction {transaction_hash} saved to {output_file}")
    return output_file

async def process_transaction_data(trade_data, output_dir):
    """Process a single transaction from WebSocket data and save it."""
    # Log the raw data for debugging
    print(f"Raw WebSocket data: {trade_data}")
    
    # Check if trade_data is a dict and has 'result'
    if not isinstance(trade_data, dict):
        print(f"Skipping non-dict response: {trade_data}")
        return
    
    if 'result' not in trade_data:
        print(f"No 'result' key in response: {trade_data}")
        return
    
    result = trade_data['result']
    
    # Ensure result is a dict (not a list or other type)
    if not isinstance(result, dict):
        print(f"Result is not a dict: {result}")
        return
    
    transaction_hash = result.get('signature', 'N/A')
    block_time = result.get('blockTime')
    
    if not transaction_hash or not block_time:
        print(f"Skipping invalid transaction: hash={transaction_hash}, block_time={block_time}")
        return
    
    await fetch_transaction_details(transaction_hash, trade_data, output_dir)

async def listen_trades(output_dir):
    """Listen to real-time trades via WebSocket and process them."""
    uri = "wss://mainnet.helius-rpc.com/?api-key=18e23183-7cc1-4373-8ccb-26ab8ea875ac"
    
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
        print(f"Subscribed to trades for market {market_address}")
        
        while True:
            try:
                response = await ws.recv()
                trade_data = json.loads(response)
                await process_transaction_data(trade_data, output_dir)
            except json.JSONDecodeError as e:
                print(f"Failed to parse WebSocket response as JSON: {response} - Error: {e}")
            except Exception as e:
                print(f"Error processing WebSocket data: {e}")
                await asyncio.sleep(1)  # Brief pause before retrying

def load_existing_signatures(file_path):
    """Load existing signatures from the input file for reference."""
    try:
        with open(file_path, 'r') as file:
            transaction_data = json.load(file)
        if isinstance(transaction_data, list):
            return {entry.get("transaction_id") for entry in transaction_data if entry.get("transaction_id")}
        return set()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading existing signatures: {e}")
        return set()

async def main():
    """Main function to run the WebSocket listener."""
    existing_signatures = load_existing_signatures(input_file)
    print(f"Loaded {len(existing_signatures)} existing signatures from {input_file}")
    
    try:
        await listen_trades(output_directory)
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
    except Exception as e:
        print(f"Fatal error in main loop: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
