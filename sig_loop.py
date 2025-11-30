import asyncio
import aiohttp
import json
import time
import psycopg2
from datetime import datetime, timedelta
import os
import traceback
import random

# Constants
TARGET_CONSTANTS_FILE = "./target_constants.json"
MIN_TRADE_AMOUNT = 0.5
API_ENDPOINT = "https://api.mainnet-beta.solana.com"
MAX_RETRIES = 5
INTERVAL = 5

db_params = {
    'dbname': 'archon_data',
    'user': 'postgres',
    'password': '#!01$Archon$10!#',
    'host': 'localhost',
    'port': '5432'
}

def load_target_constants():
    with open(TARGET_CONSTANTS_FILE, 'r') as f:
        return json.load(f)

constants = load_target_constants()
market_address = constants["target_token"]["pair_address"]
pair_address = constants["target_token"]["pair_address"]
TICKER = constants["target_token"]["ticker"].upper()
TOKEN_MINT = constants["target_token"]["mint_address"]
OUTPUT_FILE = f"json_data/{TICKER}_loop.json"
TRADE_OUTPUT_DIR = f"json_data/{TICKER}_trade_loop/"
SEA_LIFE_FILE = f"json_data/{TICKER}_sea_life.json"

async def fetch_transactions(pair_address, limit=1, until=None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [pair_address, {"limit": limit}]
    }
    if until:
        payload["params"][1]["until"] = until
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            try:
                async with session.post(API_ENDPOINT, json=payload, headers={"Content-Type": "application/json"}) as resp:
                    if resp.status == 429:
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        print(f"429 Too Many Requests for signatures, retrying in {delay:.2f}s ({attempt + 1}/{MAX_RETRIES})")
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    if "result" not in data:
                        print(f"Error fetching signatures: {data.get('error', 'Unknown error')}")
                        return []
                    return data["result"]
            except aiohttp.ClientError as e:
                print(f"Failed to fetch transactions: {e}")
                return []
        print(f"Gave up on fetching signatures after {MAX_RETRIES} retries")
        return []

async def fetch_transaction_details(signature):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
    }
    async with aiohttp.ClientSession() as session:
        for attempt in range(MAX_RETRIES):
            try:
                async with session.post(API_ENDPOINT, json=payload, headers={"Content-Type": "application/json"}) as resp:
                    if resp.status == 429:
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        print(f"429 Too Many Requests for {signature}, retrying in {delay:.2f}s ({attempt + 1}/{MAX_RETRIES})")
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("result")
            except aiohttp.ClientError as e:
                print(f"Error fetching transaction details for {signature}: {e}")
                return None
        print(f"Gave up on {signature} after {MAX_RETRIES} retries")
        return None

async def process_transaction(tx_data):
    if not tx_data:
        print("No transaction data to process")
        return None
    
    signature = tx_data.get("transaction", {}).get("signatures", ["N/A"])[0]
    block_time = tx_data.get("blockTime", int(time.time()))
    timestamp = datetime.fromtimestamp(block_time).isoformat()
    meta = tx_data.get("meta", {})
    pre_balances = meta.get("preTokenBalances", [])
    post_balances = meta.get("postTokenBalances", [])
    account_keys = tx_data.get("transaction", {}).get("message", {}).get("accountKeys", [])
    logs = meta.get("logMessages", [])
    err = meta.get("err")

    dex_programs = [
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",   # Jupiter
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",   # Lifinity
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",    # SPL Token
        "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP",  # Orca
        "M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K"    # Meteora
    ]
    has_trade = any(
        any(program in log for program in dex_programs) or 
        any(keyword in log for keyword in ["Swap", "ray_log", "Transfer", "TransferChecked", "Burn", "Mint"])
        for log in logs
    ) or TOKEN_MINT in str(tx_data)

    print(f"Checking trade activity in {signature}, has_trade: {has_trade}, TOKEN_MINT: {TOKEN_MINT}, logs (first 5): {logs[:5]}")
    if not has_trade:
        print(f"No trade activity detected in {signature}")
        return None

    trades = []
    wallet_balances = {}
    print(f"Balances for {signature} - pre: {len(pre_balances)}, post: {len(post_balances)}")
    for pre in pre_balances + [{}]:
        if pre.get("mint") == TOKEN_MINT:
            wallet = account_keys[pre.get("accountIndex")] if pre.get("accountIndex") < len(account_keys) else f"Unknown_{signature}"
            wallet_balances[wallet] = wallet_balances.get(wallet, {'pre': 0, 'post': 0})
            wallet_balances[wallet]['pre'] = pre.get("uiTokenAmount", {}).get("uiAmount", 0) or 0
    for post in post_balances + [{}]:
        if post.get("mint") == TOKEN_MINT:
            wallet = account_keys[post.get("accountIndex")] if post.get("accountIndex") < len(account_keys) else f"Unknown_{signature}"
            wallet_balances[wallet] = wallet_balances.get(wallet, {'pre': 0, 'post': 0})
            wallet_balances[wallet]['post'] = post.get("uiTokenAmount", {}).get("uiAmount", 0) or 0

    for wallet, balances in wallet_balances.items():
        pre_amount = balances['pre']
        post_amount = balances['post']
        print(f"Wallet {wallet} in {signature}: pre={pre_amount}, post={post_amount}")
        if pre_amount == post_amount:
            print(f"No balance change for {wallet} in {signature}")
            continue
        
        amount = float(abs(post_amount - pre_amount))
        if amount < MIN_TRADE_AMOUNT:
            print(f"Trade amount {amount} below threshold {MIN_TRADE_AMOUNT} for {wallet} in {signature}")
            continue
        
        trade_type = "buy" if post_amount > pre_amount else "sell"
        emoji = '🟢' if trade_type == "buy" else '🔴'
        
        trades.append({
            'transaction_id': signature,
            'timestamp': timestamp,
            'wallet_address': wallet,
            'amount': amount,
            'trade_type': trade_type,
            'emoji': emoji,
            'block_time': block_time,
            'failed': bool(err)
        })

    if not trades:
        print(f"No valid trades found in {signature} after balance check")
    return trades

async def validate_trades(trades, conn):
    if not trades:
        print("No trades to validate")
        return
    try:
        with conn.cursor() as cur:
            for trade in trades:
                timestamp = datetime.fromisoformat(trade['timestamp'])
                cur.execute(
                    """
                    INSERT INTO validator (transaction_hash, wallet_address, block_time, token_mint, pre_balance, post_balance, trade_type, transaction_emoji)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (transaction_hash) DO UPDATE SET
                        wallet_address = EXCLUDED.wallet_address,
                        block_time = EXCLUDED.block_time,
                        token_mint = EXCLUDED.token_mint,
                        pre_balance = EXCLUDED.pre_balance,
                        post_balance = EXCLUDED.post_balance,
                        trade_type = EXCLUDED.trade_type,
                        transaction_emoji = EXCLUDED.transaction_emoji
                    """,
                    (trade['transaction_id'], trade['wallet_address'], timestamp, TICKER, 0.0, trade['amount'], 
                     trade['trade_type'], trade['emoji'])
                )
            conn.commit()
            print(f"Validated and stored {len(trades)} trades in validator table")
    except psycopg2.Error as e:
        print(f"Validation error: {e}")
        conn.rollback()

class SeaLifeProcessor:
    def __init__(self, conn):
        self.conn = conn
        self.sea_life_classes = [
            ('🐋', 1000000000), ('🐳', 1000000), ('🦈', 100000), ('🐙', 50000), ('🐬', 10000),
            ('🦑', 5000), ('🐟', 1000), ('🐡', 500), ('🦭', 250), ('🦞', 100),
            ('🦀', 50), ('🐢', 25), ('🦐', 10), ('🐚', 5), ('🦪', 1),
            ('🪸', 0.5), ('🐠', 0.1), ('🐌', 0.01), ('🌊', 0)
        ]
        self.sea_life_counts = {'buy': {emoji: 0 for emoji, _ in self.sea_life_classes}, 
                              'sell': {emoji: 0 for emoji, _ in self.sea_life_classes}}
        self.total_trades = {'buy': 0, 'sell': 0}

    async def process_cycle(self, cycle_start):
        with self.conn.cursor() as cur:
            try:
                window_start = cycle_start - timedelta(seconds=120)
                print(f"Querying validator table from {window_start} to {cycle_start + timedelta(seconds=INTERVAL)}")
                cur.execute(
                    """
                    SELECT post_balance, trade_type, wallet_address, block_time, transaction_hash
                    FROM validator
                    WHERE block_time >= %s AND block_time < %s
                    """,
                    (window_start, cycle_start + timedelta(seconds=INTERVAL))
                )
                trades = cur.fetchall()
                self.sea_life_counts = {'buy': {emoji: 0 for emoji, _ in self.sea_life_classes}, 
                                      'sell': {emoji: 0 for emoji, _ in self.sea_life_classes}}
                self.total_trades = {'buy': 0, 'sell': 0}
                processed_hashes = set()

                for post_balance, trade_type, wallet_address, block_time, transaction_hash in trades:
                    if transaction_hash in processed_hashes or trade_type not in ['buy', 'sell']:
                        continue
                    processed_hashes.add(transaction_hash)
                    self.total_trades[trade_type] += 1
                    print(f"Classifying trade {transaction_hash}: type={trade_type}, amount={post_balance}")
                    classification = next((emoji for emoji, thresh in self.sea_life_classes if post_balance >= thresh), '🌊')
                    if classification != '🌊':
                        self.sea_life_counts[trade_type][classification] += 1
                    
                    amount_lamports = post_balance * 1000000
                    cur.execute(
                        """
                        INSERT INTO whale_detector (whale_wallet, detected_time, amount, token, trade_type, classification, transaction_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (transaction_hash) DO UPDATE SET
                            whale_wallet = EXCLUDED.whale_wallet,
                            detected_time = EXCLUDED.detected_time,
                            amount = EXCLUDED.amount,
                            token = EXCLUDED.token,
                            trade_type = EXCLUDED.trade_type,
                            classification = EXCLUDED.classification
                        """,
                        (wallet_address, block_time, amount_lamports, TICKER, trade_type, classification, transaction_hash)
                    )
                
                self.conn.commit()
                with open(SEA_LIFE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.sea_life_counts, f, indent=4, ensure_ascii=False)
                buy_display = ', '.join(f"{k}: {v}" for k, v in self.sea_life_counts['buy'].items())
                sell_display = ', '.join(f"{k}: {v}" for k, v in self.sea_life_counts['sell'].items())
                print(f"Sea Life Counts: {{buy: {{{buy_display}}}, sell: {{{sell_display}}}}}")
                print(f"Total Trades Processed: Buys: {self.total_trades['buy']}, Sells: {self.total_trades['sell']}")
                if not trades:
                    print("No new trades in the last 120 seconds")
                else:
                    print(f"Inserted {len(processed_hashes)} trades into whale_detector")
            except psycopg2.Error as e:
                print(f"Sea life processing error: {e}")
                self.conn.rollback()

async def main_loop(pair_address, output_file, trade_output_dir, interval=5):
    global market_address, TICKER, TOKEN_MINT, OUTPUT_FILE, TRADE_OUTPUT_DIR, SEA_LIFE_FILE
    
    conn = psycopg2.connect(**db_params)
    sea_life_processor = SeaLifeProcessor(conn)
    existing_signatures = set()
    latest_signature = None

    while True:
        try:
            constants = load_target_constants()
            new_market_address = constants["target_token"]["pair_address"]
            new_TICKER = constants["target_token"]["ticker"].upper()
            new_TOKEN_MINT = constants["target_token"]["mint_address"]
            new_OUTPUT_FILE = f"json_data/transactions/{new_TICKER}_loop.json"
            new_TRADE_OUTPUT_DIR = f"json_data/trades/{new_TICKER}_trade_loop/"
            new_SEA_LIFE_FILE = f"json_data/{new_TICKER}_sea_life.json"
            
            if (new_market_address != market_address or new_TICKER != TICKER or 
                new_TOKEN_MINT != TOKEN_MINT or new_OUTPUT_FILE != OUTPUT_FILE or 
                new_TRADE_OUTPUT_DIR != TRADE_OUTPUT_DIR or new_SEA_LIFE_FILE != SEA_LIFE_FILE):
                print(f"Target switch detected! Old: {market_address}/{TOKEN_MINT}/{TICKER}, New: {new_market_address}/{new_TOKEN_MINT}/{new_TICKER}")
                market_address = new_market_address
                pair_address = new_market_address
                TICKER = new_TICKER
                TOKEN_MINT = new_TOKEN_MINT
                OUTPUT_FILE = new_OUTPUT_FILE
                TRADE_OUTPUT_DIR = new_TRADE_OUTPUT_DIR
                SEA_LIFE_FILE = new_SEA_LIFE_FILE
                existing_signatures.clear()
                latest_signature = None

            cycle_start = datetime.now()
            print(f"\nFetching latest transaction for {TICKER} pair {pair_address} at {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")

            signatures = await fetch_transactions(pair_address, 1, until=latest_signature)
            if not signatures:
                print("No new signatures fetched")
            else:
                signature = signatures[0]["signature"]
                if signature not in existing_signatures:
                    print(f"Processing new transaction: {signature}")
                    tx_details = await fetch_transaction_details(signature)
                    if tx_details:
                        trades = await process_transaction(tx_details)
                        if trades:
                            print(f"Parsed trades for {signature}:")
                            for trade in trades:
                                print(f"  - {trade['emoji']} {trade['trade_type']} {trade['amount']} by {trade['wallet_address']} at {trade['timestamp']}")
                            await validate_trades(trades, conn)
                        existing_signatures.add(signature)
                        latest_signature = signature
                else:
                    print(f"Transaction {signature} already processed")

            await sea_life_processor.process_cycle(cycle_start)

            elapsed = (datetime.now() - cycle_start).total_seconds()
            sleep_time = max(0, interval - elapsed)
            print(f"Sleeping for {sleep_time:.2f} seconds...")
            await asyncio.sleep(sleep_time)

        except Exception as e:
            print(f"Main loop error: {e}")
            traceback.print_exc()
            await asyncio.sleep(interval)

    conn.close()
    print("Shutting down")

if __name__ == "__main__":
    asyncio.run(main_loop(pair_address, OUTPUT_FILE, TRADE_OUTPUT_DIR, INTERVAL))
