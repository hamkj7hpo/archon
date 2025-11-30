import time
import requests
import json

def get_account_info(token_address):
    url = f'https://api.mainnet-beta.solana.com'
    headers = {'Content-Type': 'application/json'}
    
    params = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [token_address, {"encoding": "jsonParsed"}]
    }
    
    response = requests.post(url, json=params, headers=headers)
    return response.json()

def track_account_changes(token_address, check_interval=5):
    prev_token_balance = None

    while True:
        try:
            account_info = get_account_info(token_address)
            account_data = account_info.get('result', {}).get('value', {})

            if 'data' in account_data:
                if isinstance(account_data['data'], list):
                    print("Data field is a list. Skipping token balance extraction.")
                else:
                    token_balance = account_data.get('data', {}).get('parsed', {}).get('info', {}).get('tokenAmount', {}).get('uiAmount', 'Unknown')
                    if prev_token_balance != token_balance:
                        print(f"Token Balance: {token_balance}")
                        prev_token_balance = token_balance
                    else:
                        print(f"Token Balance: No change")
            
            lamports_balance = account_data.get('lamports', 'Unknown')
            print(f"Lamports Balance: {lamports_balance}")
            
            # You can also print other details for debugging
            full_account_state = json.dumps(account_data, indent=4)
            print(f"Full Account State: {full_account_state}")
            
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(check_interval)

# Replace with the actual token address you want to track
token_address = "YourTokenAddressHere"
track_account_changes(token_address, check_interval=5)  # Check every 5 seconds
