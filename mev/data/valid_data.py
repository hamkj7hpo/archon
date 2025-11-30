import json
import psycopg2
from datetime import datetime

# Database connection parameters
DB_PARAMS = {
    "dbname": "archon_data",
    "user": "postgres",
    "password": "!00$bMw$00!",
    "host": "localhost",
    "port": "5432"
}

# The known Bonk token mint address
BONK_MINT_ADDRESS = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

def insert_into_db(data):
    """
    Inserts transaction data into the database without checking for duplicates.
    """
    try:
        connection = psycopg2.connect(**DB_PARAMS)
        cursor = connection.cursor()

        # SQL query for inserting data
        query = """
            INSERT INTO validator (
                transaction_hash,
                block_time,
                wallet_address,
                token_mint,
                pre_balance,
                post_balance,
                trade_type
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s);
        """
        
        cursor.execute(query, (
            data['transaction_hash'],
            data['block_time'],
            data['wallet_address'],
            data['token_mint'],
            data['pre_balance'],
            data['post_balance'],
            data['trade_type']
        ))

        connection.commit()  # Committing the changes
        
        if cursor.rowcount > 0:
            print(f"Data inserted successfully: {data}")
        else:
            print(f"No new data inserted: {data}")
    
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        if connection:
            cursor.close()
            connection.close()

def parse_transaction_file(file_path):
    try:
        print(f"Opening file: {file_path}")  # Debugging log
        with open(file_path, 'r') as file:
            response_json = json.load(file)
        
        if isinstance(response_json, dict):
            transaction = response_json.get("result", {})
            parse_transaction(transaction)
        elif isinstance(response_json, list):
            for item in response_json:
                parse_transaction(item)
        else:
            print("Unexpected JSON format")
            return

    except Exception as e:
        print(f"Error parsing transaction file: {e}")

def parse_transaction(transaction):
    if not transaction:
        print("Invalid transaction data")
        return None

    meta = transaction.get("meta", {})
    message = transaction.get("transaction", {}).get("message", {})
    account_keys = message.get("accountKeys", [])
    pre_balances = meta.get("preBalances", [])
    post_balances = meta.get("postBalances", [])
    pre_token_balances = meta.get("preTokenBalances", [])
    post_token_balances = meta.get("postTokenBalances", [])
    block_time = transaction.get("blockTime")

    # Format the timestamp
    timestamp = datetime.utcfromtimestamp(block_time).isoformat() if block_time else None

    # Process token transfers for Bonk
    for pre, post in zip(pre_token_balances, post_token_balances):
        account_index = pre.get("accountIndex")
        token_mint = pre.get("mint")

        # Skip if the transaction is not for Bonk token
        if token_mint != BONK_MINT_ADDRESS:
            continue

        wallet_address = account_keys[account_index] if account_index is not None and account_index < len(account_keys) else "Unknown"
        pre_amount = pre.get("uiTokenAmount", {}).get("uiAmount")
        post_amount = post.get("uiTokenAmount", {}).get("uiAmount")

        # Skip invalid or missing amounts
        if pre_amount is None or post_amount is None:
            continue

        # Determine trade type
        if post_amount > pre_amount:
            trade_type = "buy"
        elif pre_amount > post_amount:
            trade_type = "sell"
        else:
            trade_type = "hold"  # No change in balance

        data = {
            "transaction_hash": transaction.get("transaction", {}).get("signatures", ["Unknown"])[0],  # Use the first signature as the hash
            "block_time": timestamp,
            "wallet_address": wallet_address,
            "token_mint": token_mint,
            "pre_balance": pre_amount,
            "post_balance": post_amount,
            "trade_type": trade_type
        }

        insert_into_db(data)

    # Process native SOL transfers, ignoring non-Bonk transactions
    for i, (pre_balance, post_balance) in enumerate(zip(pre_balances, post_balances)):
        if pre_balance is not None and post_balance is not None and pre_balance != post_balance:
            wallet_address = account_keys[i] if i < len(account_keys) else "Unknown"
            sol_change = (post_balance - pre_balance) / 1e9  # Convert lamports to SOL
            trade_type = "buy" if sol_change > 0 else "sell"

            # Only log SOL transactions if they are associated with Bonk swaps
            if any(token.get("mint") == BONK_MINT_ADDRESS for token in pre_token_balances):
                data = {
                    "transaction_hash": transaction.get("transaction", {}).get("signatures", ["Unknown"])[0],  # Use the first signature as the hash
                    "block_time": timestamp,
                    "wallet_address": wallet_address,
                    "token_mint": "SOL",
                    "pre_balance": pre_balance,
                    "post_balance": post_balance,
                    "trade_type": trade_type
                }
                insert_into_db(data)

# File path to the JSON data
file_path = "json_data/trades/bonk_trades/2rfiDywksmNRkh2hotu1T6MYmd9zpRqsx74b5SQ9Z6bdUuTAgdaDmHz1phzHMD5JK7CT1S2KZhtBZoPpywjre5pw.json"

# Parse and print the results
parse_transaction_file(file_path)
