from solana.rpc.api import Client
from solana import PubKey  # Import the PublicKey class
from datetime import datetime, timedelta
from collections import defaultdict
import time

RPC_URL = "https://api.mainnet-beta.solana.com"
TOKEN_ACCOUNT = "BjZKz1z4UMjJPvPfKwTwjPErVBWnewnJFvcZB6minymy"  # Replace with your target token address
DAYS_TO_FETCH = 30

solana_client = Client(RPC_URL)

def fetch_transactions(account_address, days_to_fetch):
    """Fetch transaction signatures for the last N days."""
    account_pubkey = PublicKey(account_address)  # Convert string address to PublicKey
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_to_fetch)
    
    fetched_signatures = []
    before_signature = None
    
    while True:
        response = solana_client.get_signatures_for_address(
            account_pubkey, before=before_signature, limit=50
        )
        if not response["result"]:
            break

        for entry in response["result"]:
            block_time = entry.get("blockTime")
            if block_time is None:
                continue
            
            # Convert block timestamp to datetime
            tx_time = datetime.fromtimestamp(block_time)
            if tx_time < start_time:
                return fetched_signatures

            fetched_signatures.append(entry["signature"])
            before_signature = entry["signature"]

        time.sleep(0.5)  # Avoid rate limiting

    return fetched_signatures

def fetch_transaction_details(signature):
    """Fetch transaction details using a signature."""
    response = solana_client.get_transaction(signature)
    if response["result"]:
        return response["result"]
    return None

def analyze_transactions(signatures):
    """Analyze transactions to find the most active wallets."""
    wallet_activity = defaultdict(int)

    for signature in signatures:
        tx_data = fetch_transaction_details(signature)
        if not tx_data:
            continue

        # Extract wallet addresses involved in the transaction
        transaction_message = tx_data["transaction"]["message"]
        accounts = transaction_message.get("accountKeys", [])
        
        for account in accounts:
            wallet_activity[account] += 1

        time.sleep(0.2)  # Avoid rate limiting

    # Sort by activity count
    sorted_wallets = sorted(wallet_activity.items(), key=lambda x: x[1], reverse=True)
    return sorted_wallets

def main():
    print(f"Fetching transactions for the last {DAYS_TO_FETCH} days...")
    signatures = fetch_transactions(TOKEN_ACCOUNT, DAYS_TO_FETCH)

    if not signatures:
        print("No transactions found.")
        return

    print(f"Fetched {len(signatures)} transaction signatures.")
    active_wallets = analyze_transactions(signatures)

    print("\nMost Active Wallets in the Last 30 Days:")
    for wallet, count in active_wallets[:10]:  # Display top 10 active wallets
        print(f"{wallet}: {count} transactions")

if __name__ == "__main__":
    main()
