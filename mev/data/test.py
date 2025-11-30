import requests
import json
import time

def fetch_signatures_for_address(token_address, limit=1, before=None):
    """
    Fetch a single transaction signature for a given Solana token address.
    """
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

    # Fetch the data from the Solana API
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching data: {response.status_code}")
        return None

def extract_transaction_data(transaction):
    """
    Extract relevant fields from the transaction data for whale detection.
    """
    if not transaction:
        return None
    
    meta = transaction.get("meta", {})
    message = transaction.get("message", {})
    
    account_keys = message.get("accountKeys", [])
    
    # Safe extraction of source and destination with fallback values
    source = account_keys[0] if len(account_keys) > 0 else "N/A"
    destination = account_keys[1] if len(account_keys) > 1 else "N/A"
    
    # Return detailed information for whale detection
    return {
        'transaction_id': transaction.get('signature'),
        'timestamp': transaction.get('blockTime'),
        'confirmation_status': transaction.get('confirmationStatus'),
        'slot': transaction.get('slot'),
        'fee': meta.get("fee", 0),
        'amount': meta.get("postTokenBalances", [{}])[0].get("uiTokenAmount", {}).get("uiAmount", 0),
        'source': source,
        'destination': destination,
        'status': meta.get("status", {}).get("Ok", "Failed"),
        'token_amount': meta.get("postTokenBalances", [{}])[0].get("uiTokenAmount", {}).get("amount", 0),
        'instructions': message.get("instructions"),
        'log_messages': meta.get("logMessages"),
    }

def save_transaction_details(token_address):
    """
    Fetch and process the transaction details for a given token address.
    """
    # Fetch the latest transaction signatures
    signatures_data = fetch_signatures_for_address(token_address)
    
    if not signatures_data or "result" not in signatures_data:
        print(f"Failed to retrieve signatures for address {token_address}.")
        return
    
    # Process the fetched data
    for tx in signatures_data["result"]:
        tx_hash = tx.get('signature')
        
        # Fetch full transaction details
        transaction_data = fetch_transaction_details(tx_hash)
        
        if transaction_data:
            # Print the entire raw response for debugging
            print(f"Raw Transaction Data for {tx_hash}: {json.dumps(transaction_data, indent=2)}")
            
            # Extract relevant transaction details for whale detection
            tx_details = extract_transaction_data(transaction_data)
            
            if tx_details:
                # Print the detailed information (whale detection)
                print(json.dumps(tx_details, indent=2))

            # Print all the keys in the raw transaction response
            print("\nAll keys in the raw transaction data:")
            print_keys(transaction_data)
        
        # Wait before fetching the next transaction to avoid rate-limiting
        time.sleep(4)  # Delay between fetches to avoid hitting rate limits

def fetch_transaction_details(tx_hash):
    """
    Fetch the full transaction details for a given transaction signature.
    """
    url = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_hash,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching transaction data for {tx_hash}: {response.status_code}")
        return None

def print_keys(data, parent_key=''):
    """
    Recursively prints all keys in a nested dictionary or list.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{parent_key}.{key}" if parent_key else key
            print(full_key)
            print_keys(value, full_key)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            full_key = f"{parent_key}[{index}]"
            print(full_key)
            print_keys(item, full_key)

# Example usage: Pass the token address to get transaction details
token_address = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"  # Replace with your token address
save_transaction_details(token_address)
