import requests
import json
import time
import psycopg2  # PostgreSQL adapter for Python

# Step 1: Database connection setup
def connect_to_db():
    return psycopg2.connect(
        dbname="archon_data", 
        user="postgres", 
        password="!00$bMw$00!", 
        host="localhost", 
        port="5432"
    )

# Step 2: Check if a transaction exists in the database
def transaction_exists(db_conn, transaction_hash):
    with db_conn.cursor() as cursor:
        query = "SELECT 1 FROM validator WHERE transaction_hash = %s LIMIT 2;"
        cursor.execute(query, (transaction_hash,))
        return cursor.fetchone() is not None

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
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching data: {response.status_code}")
        return None

# Step 4: Process the data and check for duplicates
def process_and_check_duplicates(raw_data, db_conn):
    duplicates = 0
    unique_data = []
    
    if 'result' in raw_data:
        for tx in raw_data['result']:
            if transaction_exists(db_conn, tx['signature']):
                duplicates += 1
            else:
                unique_data.append({
                    'transaction_id': tx['signature'],
                    'timestamp': tx.get('blockTime'),
                    'confirmation_status': tx.get('confirmationStatus'),
                    'slot': tx.get('slot')
                })
    return unique_data, duplicates

# Step 4: Remove duplicates from the saved JSON
def remove_duplicates_from_json(filename, db_conn):
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
        
        unique_data = []
        duplicates = 0
        
        for entry in data:
            if transaction_exists(db_conn, entry['transaction_id']):
                duplicates += 1
            else:
                unique_data.append(entry)
        
        # Save the cleaned data back to the file
        with open(filename, 'w') as file:
            json.dump(unique_data, file, indent=4)
        
        print(f"{duplicates} duplicates removed from {filename}")
    except FileNotFoundError:
        print(f"File {filename} not found.")
    except json.JSONDecodeError:
        print(f"Error decoding JSON in {filename}.")

# Step 5: Save to JSON
def save_to_json(data, filename):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file, indent=4)

# Step 6: Main function to fetch, check for duplicates, and clean the JSON
def fetch_and_clean_data(token_address, target_entries=5000):
    all_data = []
    before = None
    total_duplicates = 0
    filename = 'json_data/transactions/batcat_loop.json'

    # Connect to the database
    db_conn = connect_to_db()

    try:
        while len(all_data) < target_entries:
            raw_data = fetch_historical_data(token_address, before=before)
            if raw_data and 'result' in raw_data and raw_data['result']:
                unique_data, duplicates = process_and_check_duplicates(raw_data, db_conn)
                all_data.extend(unique_data)
                total_duplicates += duplicates
                
                # Update the 'before' parameter for the next batch
                before = raw_data['result'][-1]['signature']
                print(f"Fetched {len(all_data)} entries so far, {duplicates} duplicates found in this batch.")
                
                # To avoid hitting rate limits, pause briefly between requests
                time.sleep(1)
            else:
                print("No more data available or an error occurred.")
                break
        
        save_to_json(all_data, filename)
        print(f"Data saved with {len(all_data)} unique entries to {filename}")
        
        # Remove duplicates from the saved file
        remove_duplicates_from_json(filename, db_conn)
    finally:
        db_conn.close()

# Example usage
if __name__ == "__main__":
    token_address = "2tGE3AEuQxsrMtBZK1vqAVJ2HvVUtUU82fcAPPTvDsDn"  # Replace with actual token address
    fetch_and_clean_data(token_address)
