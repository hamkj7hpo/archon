import requests
import json
import time
import os

# Step 1: Load existing data from JSON file
def load_existing_data(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return json.load(file)
    return []

# Step 2: Save updated data to JSON
def save_to_json(data, filename):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

# Step 3: Fetch historical data with pagination
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
    
    for attempt in range(5):  # Retry up to 5 times
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            print("Rate limit hit. Retrying after delay...")
            time.sleep(2 ** attempt)  # Exponential backoff
        else:
            print(f"Error fetching data: {response.status_code}")
            return None
    return None

# Step 4: Process data and prevent duplicates
def process_data(raw_data, existing_hashes):
    processed_data = []
    if 'result' in raw_data:
        for tx in raw_data['result']:
            if tx['signature'] not in existing_hashes:
                processed_data.append({
                    'transaction_id': tx['signature'],
                    'timestamp': tx['blockTime'],
                    'confirmation_status': tx['confirmationStatus'],
                    'slot': tx['slot']
                })
    return processed_data

# Step 5: Main function to fetch data iteratively
def fetch_all_data(token_address, target_entries=10000, filename='json_data/transactions/bonk_tx.json'):
    existing_data = load_existing_data(filename)
    existing_hashes = {entry['transaction_id'] for entry in existing_data}
    all_data = existing_data
    before = None

    while len(all_data) - len(existing_data) < target_entries:
        raw_data = fetch_historical_data(token_address, before=before)
        if raw_data and 'result' in raw_data and raw_data['result']:
            new_data = process_data(raw_data, existing_hashes)
            all_data.extend(new_data)
            
            before = raw_data['result'][-1]['signature']
            print(f"Fetched {len(all_data) - len(existing_data)} new entries so far...")
            
            existing_hashes.update(entry['transaction_id'] for entry in new_data)
            time.sleep(1)  # Pause briefly between requests
        else:
            print("No more data available or an error occurred.")
            break
    
    save_to_json(all_data, filename)
    print(f"Data saved with {len(all_data)} total entries to {filename}")

# Example usage
token_address = "BjZKz1z4UMjJPvPfKwTwjPErVBWnewnJFvcZB6minymy"  # Replace with actual token address
fetch_all_data(token_address)
