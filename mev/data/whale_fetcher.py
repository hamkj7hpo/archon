import requests
import json
import time
import tempfile
import random


def fetch_signatures_for_address(token_address, before=None, max_retries=5):
    url = "https://api.mainnet-beta.solana.com/"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [token_address, {"before": before}]
    }

    retries = 0
    while retries < max_retries:
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()  # Will raise an exception for HTTP errors
            return response.json()
        except requests.exceptions.HTTPError as err:
            if response.status_code == 429:
                print("Rate limit hit, retrying...")
                retries += 1
                time.sleep(2 ** retries)  # Exponential backoff
            else:
                print(f"Request failed: {err}")
                break
        except RequestException as e:
            print(f"Request failed: {e}")
            break
    return None  # Return None if max retries exceeded or request fails

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
                "maxSupportedTransactionVersion": 0  # Reintroduce this parameter
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transaction data for {tx_hash}: {e}")
        return None

def is_transaction_successful(transaction_data):
    """
    Checks if the transaction is successful by inspecting the status.
    """
    meta = transaction_data.get("meta", {})
    transaction_status = meta.get("status", {}).get("Ok", "Failed")
    
    return transaction_status == "Ok"

def save_raw_data_to_tempfile(data):
    """
    Save raw transaction data to a temporary file.
    """
    with tempfile.NamedTemporaryFile(delete=False, mode='w', newline='', encoding='utf-8') as temp_file:
        json.dump(data, temp_file, indent=2)
        return temp_file.name

def extract_transaction_data_from_file(temp_file_path):
    """
    Extract transaction details from a temporary file.
    """
    with open(temp_file_path, 'r', encoding='utf-8') as temp_file:
        transaction_data = json.load(temp_file)
    
    return extract_transaction_data(transaction_data)

def extract_transaction_data(transaction):
    """
    Extract relevant fields from the transaction data for whale detection.
    """
    if not transaction:
        print("Transaction data is missing!")
        return None
    
    meta = transaction.get("meta", {})
    message = transaction.get("message", {})
    
    account_keys = message.get("accountKeys", [])
    
    source = account_keys[0] if len(account_keys) > 0 else "N/A"
    destination = account_keys[1] if len(account_keys) > 1 else "N/A"
    
    confirmation_status = transaction.get('confirmationStatus', 'Not Confirmed')
    transaction_status = meta.get("status", {}).get("Ok", "Failed")
    
    log_messages = meta.get("logMessages", [])
    
    tx_details = {
        'transaction_id': transaction.get('signature'),
        'timestamp': transaction.get('blockTime'),
        'confirmation_status': confirmation_status,
        'slot': transaction.get('slot'),
        'fee': meta.get("fee", 0),
        'amount': meta.get("postTokenBalances", [{}])[0].get("uiTokenAmount", {}).get("uiAmount", 0),
        'source': source,
        'destination': destination,
        'status': transaction_status,
        'token_amount': meta.get("postTokenBalances", [{}])[0].get("uiTokenAmount", {}).get("amount", 0),
        'instructions': message.get("instructions"),
        'log_messages': log_messages,
    }
    
    return tx_details

def save_transaction_details(token_address):
    """
    Fetch and process the transaction details for a given token address.
    """
    before = None
    retries = 0  # Add a retry counter
    while True:
        try:
            # Fetch the latest transaction signatures
            signatures_data = fetch_signatures_for_address(token_address, before=before)
            
            if not signatures_data or "result" not in signatures_data:
                print(f"Failed to retrieve signatures for address {token_address}.")
                continue

            # Process the fetched data
            for tx in signatures_data["result"]:
                tx_hash = tx.get('signature')
                before = tx.get('signature')  # Update before to the latest signature

                # Fetch full transaction details
                transaction_data = fetch_transaction_details(tx_hash)
                
                if transaction_data:
                    # Check if the transaction is successful (confirmation status is "Ok")
                    if is_transaction_successful(transaction_data):
                        print(f"Successful transaction detected: {tx_hash}")
                        
                        # Save raw transaction data to a temporary file
                        temp_file_path = save_raw_data_to_tempfile(transaction_data)
                        print("Raw data saved.")
                        
                        # Extract transaction details from the temp file
                        tx_details = extract_transaction_data_from_file(temp_file_path)
                        
                        if tx_details:
                            print("Parsing data success. Extracted transaction details:")
                            print(json.dumps(tx_details, indent=2))
                    else:
                        print(f"Skipping transaction {tx_hash} due to failure or pending confirmation.")
                
                # Wait before fetching the next transaction to avoid rate-limiting
                time.sleep(random.uniform(2, 5))  # Randomize delay to avoid rate-limiting

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            retries += 1
            if retries > 5:
                print("Max retries reached. Sleeping before retrying...")
                time.sleep(30)
                retries = 0
            else:
                print("Retrying after a short delay...")
                time.sleep(random.uniform(5, 10))  # Delay before retrying

        print("Waiting for the next transaction...")

# Example usage: Pass the token address to get transaction details
token_address = "HYSaskwSLTT1fN9S7mopGCxuT48mEEFW4rXhfn8pump"  # Replace with your token address
save_transaction_details(token_address)
