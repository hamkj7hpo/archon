import asyncio
import websockets
import json
import aiohttp
import time
import psycopg2
from datetime import datetime, timedelta
import os
import traceback

# Constants
TARGET_CONSTANTS_FILE = "/home/joshua/archon/mev/data/target_constants.json"
MIN_TRADE_AMOUNT = 0.001

def load_target_constants():
    try:
        with open(TARGET_CONSTANTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        default = {
            "target_token": {
                "mint_address": "9fmdkQipJK2teeUv53BMDXi52uRLbrEvV38K8GBNkiM7",  # Replace with actual mint
                "pair_address": "CniPCE4b3s8gSUPhUiyMjXnytrEqUrMfSsnbBjLCpump",
                "ticker": "BABY"
            }
        }
        with open(TARGET_CONSTANTS_FILE, 'w') as f:
            json.dump(default, f, indent=4)
        return default

constants = load_target_constants()
market_address = constants["target_token"]["pair_address"]
pair_address = constants["target_token"]["pair_address"]
TICKER = constants["target_token"]["ticker"].upper()
TOKEN_MINT = constants["target_token"]["mint_address"]
OUTPUT_FILE = f"json_data/transactions/{TICKER}_loop.json"
TRADE_OUTPUT_DIR = f"json_data/trades/{TICKER}_trade_loop/"
SEA_LIFE_FILE = f"json_data/{TICKER}_sea_life.json"
INTERVAL = 5

db_params = {
    'dbname': 'archon_data',
    'user': 'postgres',
    'password': '!00$bMw$00!',
    'host': 'localhost',
    'port': '5432'
}

async def fetch_transaction_details(signature):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
    }
    retries = 3
    async with aiohttp.ClientSession() as session:
        for attempt in range(retries):
            try:
                async with session.post("wss://api.mainnet-beta.solana.com", 
                                      json=payload, headers={"Content-Type": "application/json"}) as response:
                    response.raise_for_status()
                    return (await response.json()).get("result")
            except aiohttp.ClientError as e:
                if response.status == 503:
                    print(f"503 Service Unavailable for {signature}, retrying ({attempt + 1}/{retries})...")
                    await asyncio.sleep(0.2 * (2 ** attempt))
                else:
                    print(f"Error fetching transaction details for {signature}: {e}")
                    return None
        print(f"Failed to fetch transaction details for {signature} after {retries} retries")
        return None

async def listen_trades(output_file, trade_output_dir, validator_queue):
    global TOKEN_MINT
    uri = "wss://api.mainnet-beta.solana.com"
    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=60) as ws:
                sub_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "logsSubscribe",
                    "params": [{"mentions": [TOKEN_MINT]}, {"commitment": "finalized"}]
                }
                await ws.send(json.dumps(sub_request))
                print(f"Subscribed to transactions for {TICKER} token {TOKEN_MINT}")
                while True:
                    response = await ws.recv()
                    trade_data = json.loads(response)
                    print("Real-time trade received:", trade_data)
                    processed_trades = await process_realtime_trade(trade_data, output_file, trade_output_dir)
                    if processed_trades:
                        print(f"Queuing {len(processed_trades)} trades to validator, queue size: {validator_queue.qsize()}")
                        await validator_queue.put(processed_trades)
        except Exception as e:
            print(f"WebSocket error: {e}")
            print("Reconnecting in 2 seconds...")
            await asyncio.sleep(2)

async def process_realtime_trade(trade_data, output_file, trade_output_dir):
    global TICKER, TOKEN_MINT
    if not isinstance(trade_data, dict) or ('id' in trade_data and 'method' not in trade_data):
        print("Skipping subscription confirmation")
        return None
    if trade_data.get('method') != 'logsNotification' or 'params' not in trade_data:
        print(f"Unexpected message format: {trade_data}")
        return None
    
    params = trade_data['params']
    result = params.get('result', {})
    value = result.get('value', {})
    transaction_hash = value.get('signature', 'N/A')
    slot = result.get('context', {}).get('slot', None)

    if not transaction_hash or not slot:
        print(f"Invalid trade data: hash={transaction_hash}, slot={slot}")
        return None

    full_tx = await fetch_transaction_details(transaction_hash)
    if not full_tx:
        print(f"Failed to fetch transaction details for {transaction_hash}")
        return None

    block_time = full_tx.get("blockTime", int(time.time()))
    timestamp = datetime.fromtimestamp(block_time).isoformat()
    meta = full_tx.get("meta", {})
    pre_token_balances = meta.get("preTokenBalances", [])
    post_token_balances = meta.get("postTokenBalances", [])
    account_keys = full_tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    logs = meta.get("logMessages", [])

    dex_programs = [
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP",
        "M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K"
    ]
    has_trade = any(
        any(program in log for program in dex_programs) or 
        any(keyword in log for keyword in ["Swap", "ray_log", "Transfer", "TransferChecked", "Burn", "Mint"])
        for log in logs
    ) or TOKEN_MINT in str(full_tx)
    if not has_trade:
        print(f"No trade activity detected in logs for {transaction_hash}: {logs}")
        return None

    trades = []
    processed_wallets = set()
    print(f"Processing balances for {transaction_hash} - {len(pre_token_balances)} pre, {len(post_token_balances)} post")

    wallet_balances = {}
    for pre in pre_token_balances + [{}]:
        if pre.get("mint") == TOKEN_MINT:
            wallet = account_keys[pre.get("accountIndex")] if pre.get("accountIndex") < len(account_keys) else f"Unknown_{transaction_hash}"
            wallet_balances[wallet] = wallet_balances.get(wallet, {'pre': 0, 'post': 0})
            wallet_balances[wallet]['pre'] = pre.get("uiTokenAmount", {}).get("uiAmount", 0) or 0
    for post in post_token_balances + [{}]:
        if post.get("mint") == TOKEN_MINT:
            wallet = account_keys[post.get("accountIndex")] if post.get("accountIndex") < len(account_keys) else f"Unknown_{transaction_hash}"
            wallet_balances[wallet] = wallet_balances.get(wallet, {'pre': 0, 'post': 0})
            wallet_balances[wallet]['post'] = post.get("uiTokenAmount", {}).get("uiAmount", 0) or 0

    for wallet, balances in wallet_balances.items():
        if wallet in processed_wallets:
            continue
        pre_amount = balances['pre']
        post_amount = balances['post']
        print(f"Balance for {transaction_hash}, wallet={wallet}: pre_amount={pre_amount}, post_amount={post_amount}")
        
        if pre_amount == post_amount:
            print(f"Skipping hold trade for {transaction_hash}, wallet={wallet} - no amount change")
            continue
        
        amount = float(abs(post_amount - pre_amount))
        trade_type = "buy" if post_amount > pre_amount else "sell"
        emoji = '🟢' if trade_type == "buy" else '🔴'
        
        processed_wallets.add(wallet)
        trades.append({
            'transaction_id': transaction_hash,
            'timestamp': timestamp,
            'wallet_address': wallet,
            'amount': amount,
            'trade_type': trade_type,
            'emoji': emoji,
            'block_time': block_time
        })

    if not trades:
        print(f"No valid buy/sell activity in {transaction_hash}")
        return None

    save_to_json_file(trades, output_file, append=True)
    trade_output_file = f"{trade_output_dir}/{transaction_hash}.json"
    save_trade_details(trade_data, trade_output_file)
    print(f"Processed trade: {transaction_hash}, slot: {slot}, {len(trades)} trades extracted, block_time: {timestamp}")
    return trades

def save_trade_details(trade_data, output_file):
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(trade_data, f, indent=4, ensure_ascii=False)
        print(f"Saved trade details to {output_file}")
    except Exception as e:
        print(f"Error saving trade details: {e}")

def save_to_json_file(data, output_file, append=False):
    try:
        clean_data = [{k: (str(v) if isinstance(v, datetime) else v) for k, v in item.items()} for item in data]
        if not append or not os.path.exists(output_file):
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, indent=4, ensure_ascii=False)
        else:
            with open(output_file, 'r+', encoding='utf-8') as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    print(f"Corrupted JSON in {output_file}, overwriting")
                    existing_data = []
                existing_data.extend(clean_data)
                f.seek(0)
                json.dump(existing_data, f, indent=4, ensure_ascii=False)
                f.truncate()
        print(f"Saved {len(clean_data)} transactions to {output_file} (append={append})")
    except Exception as e:
        print(f"Error saving data: {e}")

async def validate_trades(validator_queue, conn):
    print("Starting trade validation task")
    while True:
        try:
            trades = await validator_queue.get()
            if not trades:
                print("Received empty trade batch from validator queue")
                validator_queue.task_done()
                continue
            with conn.cursor() as cur:
                try:
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
            validator_queue.task_done()
        except Exception as e:
            print(f"Validation task error: {e}")
            traceback.print_exc()
            validator_queue.task_done()

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
                    print(f"Processing trade {transaction_hash}: type={trade_type}, amount={post_balance}, time={block_time}")
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
                if trades:
                    print(f"Inserted {len(processed_hashes)} trades into whale_detector")
            except psycopg2.Error as e:
                print(f"Sea life processing error: {e}")
                self.conn.rollback()

async def main_loop(token_address, output_file, trade_output_dir, interval=5):
    global market_address, pair_address, TICKER, TOKEN_MINT, OUTPUT_FILE, TRADE_OUTPUT_DIR, SEA_LIFE_FILE
    
    validator_queue = asyncio.Queue(maxsize=1000)
    conn = psycopg2.connect(**db_params)
    sea_life_processor = SeaLifeProcessor(conn)

    print("Scheduling tasks")
    trade_task = asyncio.create_task(listen_trades(output_file, trade_output_dir, validator_queue))
    asyncio.create_task(validate_trades(validator_queue, conn))

    await asyncio.sleep(1)

    while True:
        try:
            constants = load_target_constants()
            new_market_address = constants["target_token"]["pair_address"]
            new_pair_address = constants["target_token"]["pair_address"]
            new_TICKER = constants["target_token"]["ticker"].upper()
            new_TOKEN_MINT = constants["target_token"]["mint_address"]
            new_OUTPUT_FILE = f"json_data/transactions/{new_TICKER}_loop.json"
            new_TRADE_OUTPUT_DIR = f"json_data/trades/{new_TICKER}_trade_loop/"
            new_SEA_LIFE_FILE = f"json_data/{new_TICKER}_sea_life.json"
            
            if (new_market_address != market_address or new_TOKEN_MINT != TOKEN_MINT or 
                new_TICKER != TICKER or new_OUTPUT_FILE != OUTPUT_FILE or 
                new_TRADE_OUTPUT_DIR != TRADE_OUTPUT_DIR or new_SEA_LIFE_FILE != SEA_LIFE_FILE):
                print(f"Target switch detected! Old: {market_address}/{TOKEN_MINT}/{TICKER}, New: {new_market_address}/{new_TOKEN_MINT}/{new_TICKER}")
                market_address = new_market_address
                pair_address = new_pair_address
                TICKER = new_TICKER
                TOKEN_MINT = new_TOKEN_MINT
                OUTPUT_FILE = new_OUTPUT_FILE
                TRADE_OUTPUT_DIR = new_TRADE_OUTPUT_DIR
                SEA_LIFE_FILE = new_SEA_LIFE_FILE
                
                trade_task.cancel()
                try:
                    await trade_task
                except asyncio.CancelledError:
                    print("Old trade listener cancelled")
                trade_task = asyncio.create_task(listen_trades(OUTPUT_FILE, TRADE_OUTPUT_DIR, validator_queue))
        
            cycle_start = datetime.now().replace(second=(datetime.now().second // interval) * interval, microsecond=0)
            await asyncio.sleep(interval)
            
            print(f"\n=== Cycle Kickoff at {cycle_start.strftime('%Y-%m-%d %H:%M:%S')} for {TICKER} ===")
            await sea_life_processor.process_cycle(cycle_start)
            
            sea_life_total_buys = sea_life_processor.total_trades['buy']
            sea_life_total_sells = sea_life_processor.total_trades['sell']
            
            print(f"\nCycle Totals at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}:")
            print(f"Trade Totals: 🟢 {sea_life_total_buys}, 🔴 {sea_life_total_sells}")
            
            buy_display = ', '.join(f'{k}: {v}' for k, v in sea_life_processor.sea_life_counts['buy'].items())
            sell_display = ', '.join(f'{k}: {v}' for k, v in sea_life_processor.sea_life_counts['sell'].items())
            print(f"Sea Life Counts: {{buy: {{{buy_display}}}, sell: {{{sell_display}}}}}")
            
            print("Cycle completed")
        except Exception as e:
            print(f"Main loop error: {e}")
            traceback.print_exc()
            break

    conn.close()
    print("Shutting down")

if __name__ == "__main__":
    asyncio.run(main_loop(market_address, OUTPUT_FILE, TRADE_OUTPUT_DIR, INTERVAL))
