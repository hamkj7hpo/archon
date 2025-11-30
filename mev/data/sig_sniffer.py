import requests
import json
import time

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

# Step 3: Save to JSON
def save_to_json(data, filename):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

# Step 4: Main function to fetch data iteratively
def fetch_all_data(token_address, target_entries=10000):
    all_data = []
    before = None

    while len(all_data) < target_entries:
        raw_data = fetch_historical_data(token_address, before=before)
        if raw_data and 'result' in raw_data and raw_data['result']:
            processed_data = process_data(raw_data)
            all_data.extend(processed_data)
            
            # Update the 'before' parameter for the next batch
            before = raw_data['result'][-1]['signature']
            print(f"Fetched {len(all_data)} entries so far...")
            
            # To avoid hitting rate limits, pause briefly between requests
            time.sleep(1)
        else:
            print("No more data available or an error occurred.")
            break
    
    save_to_json(all_data, 'json_data/transactions/batcat_loop.json')
    print(f"Data saved with {len(all_data)} entries to transactions")

# Example usage
token_address = "2tGE3AEuQxsrMtBZK1vqAVJ2HvVUtUU82fcAPPTvDsDn"  # Replace with actual token address
fetch_all_data(token_address)
