import os
import json
import psycopg2
from datetime import datetime
import requests
import sys

TARGET_CONSTANTS_FILE = "/home/joshua/archon/mev/data/target_constants.json"
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/?api-key=18e23183-7cc1-4373-8ccb-26ab8ea875ac"

def load_target_constants():
    try:
        with open(TARGET_CONSTANTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        default = {
            "target_token": {
                "mint_address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                "pair_address": "some_bonk_usdc_pair",
                "ticker": "BONK"
            }
        }
        with open(TARGET_CONSTANTS_FILE, 'w') as f:
            json.dump(default, f, indent=4)
        return default

constants = load_target_constants()
market_address = constants["target_token"]["mint_address"]
pair_address = constants["target_token"]["pair_address"]
TICKER = constants["target_token"]["ticker"].upper()

db_params = {
    "dbname": "archon_data",
    "user": "postgres",
    "password": "!00$bMw$00!",
    "host": "localhost",
    "port": "5432"
}

def insert_into_db(data):
    try:
        with psycopg2.connect(**db_params) as conn:
            with conn.cursor() as cur:
                insert_query = """
                    INSERT INTO validator (
                        transaction_hash, block_time, wallet_address, token_mint, pre_balance, post_balance, trade_type
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (wallet_address, block_time) DO UPDATE SET
                        transaction_hash = EXCLUDED.transaction_hash,
                        token_mint = EXCLUDED.token_mint,
                        pre_balance = EXCLUDED.pre_balance,
                        post_balance = EXCLUDED.post_balance,
                        trade_type = EXCLUDED.trade_type
                    """
                cur.execute(insert_query, (
                    data['transaction_hash'],
                    data['block_time'],
                    data['wallet_address'],
                    data['token_mint'],
                    data.get('pre_balance', 0),
                    data.get('post_balance', 0),
                    data.get('trade_type', 'unknown')
                ))
                conn.commit()
                if cur.rowcount > 0:
                    print(f"Data inserted or updated: {data['transaction_hash']} - {data['wallet_address']} at {data['block_time']}")
                return True
    except Exception as e:
        print(f"Database error for {data.get('transaction_hash', 'unknown')}: {e}")
        return False

def fetch_transaction_details(signature):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
    }
    try:
        response = requests.post(HELIUS_RPC_URL, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        return response.json().get("result")
    except Exception as e:
        print(f"Error fetching transaction details for {signature}: {e}")
        return None

def check_existing_transactions(transaction_hashes):
    try:
        with psycopg2.connect(**db_params) as conn:
            with conn.cursor() as cur:
                query = "SELECT transaction_hash FROM validator WHERE transaction_hash IN %s"
                cur.execute(query, (tuple(transaction_hashes),))
                existing = set(row[0] for row in cur.fetchall())
                return existing
    except Exception as e:
        print(f"Error checking transactions: {e}")
        return set()

def parse_transaction(transaction, source):
    if not transaction:
        print(f"Invalid transaction data from {source}")
        return

    meta = transaction.get("meta", {})
    message = transaction.get("transaction", {}).get("message", {})
    account_keys = message.get("accountKeys", [])
    pre_balances = meta.get("preBalances", [])
    post_balances = meta.get("postBalances", [])
    pre_token_balances = meta.get("preTokenBalances", [])
    post_token_balances = meta.get("postTokenBalances", [])
    block_time = transaction.get("blockTime")

    if not block_time:
        print(f"No blockTime in transaction from {source}")
        return
    
    timestamp = datetime.utcfromtimestamp(block_time).isoformat()
    signature = transaction.get("transaction", {}).get("signatures", ["Unknown"])[0]

    # Parse token balances for the target mint first (amounts in BONK)
    token_inserted = False
    for pre, post in zip(pre_token_balances, post_token_balances):
        account_index = pre.get("accountIndex")
        token_mint = pre.get("mint")

        if token_mint != market_address:
            continue

        wallet_address = account_keys[account_index] if account_index is not None and account_index < len(account_keys) else f"Unknown_{signature}"
        pre_amount = pre.get("uiTokenAmount", {}).get("uiAmount")
        post_amount = post.get("uiTokenAmount", {}).get("uiAmount")

        if pre_amount is None or post_amount is None:
            print(f"Missing uiAmount for {market_address} in {source} - tx: {signature}")
            continue

        trade_type = "buy" if post_amount > pre_amount else "sell" if pre_amount > post_amount else "hold"
        data = {
            "transaction_hash": signature,
            "block_time": timestamp,
            "wallet_address": wallet_address,
            "token_mint": TICKER,  # Use ticker (BONK)
            "pre_balance": pre_amount,  # In BONK
            "post_balance": post_amount,  # In BONK
            "trade_type": trade_type
        }
        if insert_into_db(data):
            token_inserted = True
            break

    # If no token data, parse SOL balances
    if not token_inserted:
        for i, (pre_balance, post_balance) in enumerate(zip(pre_balances, post_balances)):
            if pre_balance is not None and post_balance is not None and pre_balance != post_balance:
                wallet_address = account_keys[i] if i < len(account_keys) else f"Unknown_{signature}_{i}"
                pre_sol = pre_balance / 1e9  # Convert Lamports to SOL
                post_sol = post_balance / 1e9
                trade_type = "buy" if post_sol > pre_sol else "sell"
                data = {
                    "transaction_hash": signature,
                    "block_time": timestamp,
                    "wallet_address": wallet_address,
                    "token_mint": "SOL",
                    "pre_balance": pre_sol,
                    "post_balance": post_sol,
                    "trade_type": trade_type
                }
                if insert_into_db(data):
                    break

def process_transaction_file(file_path):
    try:
        print(f"Processing file: {file_path}")
        with open(file_path, 'r') as f:
            transactions = json.load(f)
        
        if not isinstance(transactions, list):
            print(f"Error: {file_path} does not contain a list of transactions")
            return False
        
        transaction_hashes = [tx.get("transaction_id") for tx in transactions if tx.get("transaction_id")]
        existing_hashes = check_existing_transactions(transaction_hashes)
        new_transactions = [tx for tx in transactions if tx.get("transaction_id") not in existing_hashes]
        
        print(f"Found {len(transactions)} transactions, {len(new_transactions)} new")
        
        for tx in new_transactions:
            signature = tx.get("transaction_id")
            if not signature:
                print(f"Skipping transaction with no ID in {file_path}")
                continue
            full_transaction = fetch_transaction_details(signature)
            if full_transaction:
                parse_transaction(full_transaction, file_path)
            else:
                print(f"Failed to fetch details for {signature}")
        return True
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 trade_data_inserter.py <transaction_file>")
        sys.exit(1)
    
    transaction_file = sys.argv[1]
    if not os.path.isfile(transaction_file):
        print(f"File not found: {transaction_file}")
        sys.exit(1)
    
    success = process_transaction_file(transaction_file)
    if not success:
        sys.exit(1)
