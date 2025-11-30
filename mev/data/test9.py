import requests
import json
import time
import os

# File paths
output_file = 'json_data/transactions/bonk_tx.json'
temp_file = 'json_data/transactions/bonk_tx_temp.json'

# Step 1: Fetch historical data with pagination
def fetch_historical_data(token_address, limit=1000, before=None):
    url = "https://api.mainnet-beta.solana.com"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            token_address,
            {
                "limit": limit,
                "before": before
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 429:  # Rate limit handling
        print("Error 429. Retrying...")
        time.sleep(1)
        return fetch_historical_data(token_address, limit, before)
    else:
        print(f"Error fetching data: {response.status_code}")
        return None

# Step 2: Process the data
def process_data(raw_data):
    processed_data = []
    if 'result' in raw_data:
        for tx in raw_data['result']:
            processed_data.append({
                'transaction_id': tx['signature'],
                'timestamp': tx['blockTime'],
                'confirmation_status': tx['confirmationStatus'],
                'slot': tx['slot']
            })
    return processed_data

# Step 3: Save data incrementally
def save_progress(data, temp_path):
    with open(temp_path, 'w') as temp_file:
        json.dump(data, temp_file, indent=4)
    print(f"Progress saved. Current count: {len(data)}")

# Step 4: Load previous progress
def load_progress(temp_path):
    if os.path.exists(temp_path):
        with open(temp_path, 'r') as temp_file:
            return json.load(temp_file)
    return []

# Step 5: Fetch all data
def fetch_all_data(token_address, target_entries=10000, limit=1000):
    all_data = load_progress(temp_file)
    before = all_data[-1]['transaction_id'] if all_data else None

    while len(all_data) < target_entries:
        raw_data = fetch_historical_data(token_address, limit=limit, before=before)
        if raw_data and 'result' in raw_data and raw_data['result']:
            processed_data = process_data(raw_data)
            all_data.extend(processed_data)

            # Update 'before' parameter and save progress
            before = raw_data['result'][-1]['signature']
            save_progress(all_data, temp_file)
            print(f"Fetched {len(all_data)} entries so far...")
            
            # Pause to avoid hitting rate limits
            time.sleep(1)
        else:
            print("No more data available or an error occurred.")
            break

    # Save final data
    with open(output_file, 'w') as file:
        json.dump(all_data, file, indent=4)
    print(f"Final data saved with {len(all_data)} entries to {output_file}")

# Example usage
token_address = "BjZKz1z4UMjJPvPfKwTwjPErVBWnewnJFvcZB6minymy"  # Replace with actual token address
fetch_all_data(token_address, target_entries=20000)
