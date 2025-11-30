import asyncio
from aiohttp import web
import psycopg2
from datetime import datetime
import json



TARGET_CONSTANTS_FILE = "/home/joshua/archon/mev/data/target_constants.json"

def load_target_constants():
    try:
        with open(TARGET_CONSTANTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        default = {
            "target_token": {
                "mint_address": "7BNwDrLsyiQmGN7PKMUPtVCRMetuG6b6xLRiAhdZpump",
                "pair_address": "71LJqRFwcb1rbxNkoUURehrR7bBQJUWb775osUUPHesw",
                "ticker": "YE"
            }
        }
        with open(TARGET_CONSTANTS_FILE, 'w') as f:
            json.dump(default, f, indent=4)
        return default

constants = load_target_constants()
market_address = constants["target_token"]["pair_address"]
mint_address = constants["target_token"]["mint_address"]
TICKER = constants["target_token"]["ticker"].upper()

db_params = {
    'dbname': 'archon_data',
    'user': 'postgres',
    'password': '!00$bMw$00!',
    'host': 'localhost',
    'port': '5432'
}

validator_queue = asyncio.Queue(maxsize=1000)
whale_queue = asyncio.Queue(maxsize=1000)

async def handle_trades(request):
    trades = await request.json()
    print(f"Received trades from scraper: {trades}")
    processed_trades = []
    for trade in trades:
        processed_trade = {
            'transaction_id': f"scraped_{int(time.time()*1000)}",
            'timestamp': datetime.now().isoformat(),
            'wallet_address': "scraped_wallet",  # Placeholder
            'amount': trade['amount'],
            'trade_type': trade['type'],
            'emoji': '🟢' if trade['type'] == 'buy' else '🔴'
        }
        processed_trades.append(processed_trade)
    if processed_trades:
        await validator_queue.put(processed_trades)
    return web.Response(text="Trades received")

async def trade_task(validator_queue, whale_queue, conn):
    trade_counts = {'🟢': 0, '🔴': 0}
    column_trades = {}
    processed_hashes = set()
    
    print("Starting trade task...")
    while True:
        trades = await validator_queue.get()
        if not trades:
            validator_queue.task_done()
            continue

        tx_hash = trades[0]['transaction_id']
        if tx_hash in processed_hashes:
            print(f"Skipping duplicate batch for {tx_hash}")
            validator_queue.task_done()
            continue
        processed_hashes.add(tx_hash)

        filtered_trades = [t for t in trades if t['trade_type'] in ('buy', 'sell')]
        if not filtered_trades:
            print(f"No buy/sell trades in batch for {tx_hash}")
            validator_queue.task_done()
            continue

        print(f"Processing {len(filtered_trades)} trades, queue size: {validator_queue.qsize()}")
        with conn.cursor() as cur:
            for trade in filtered_trades:
                timestamp = datetime.fromisoformat(trade['timestamp'])
                cur.execute(
                    """
                    INSERT INTO candlestick_data (
                        token_pair, timestamp, open, high, low, close, ticker, token_mint, 
                        transaction_type, transaction_emoji
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (timestamp, token_pair) DO UPDATE SET
                        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
                        transaction_type = EXCLUDED.transaction_type, transaction_emoji = EXCLUDED.transaction_emoji
                    """,
                    (
                        market_address, timestamp, trade['amount'], trade['amount'], trade['amount'], trade['amount'],
                        TICKER, mint_address, trade['trade_type'], trade['emoji']
                    )
                )
                trade_counts[trade['emoji']] += 1
            conn.commit()
            print(f"Inserted {len(filtered_trades)} trades, totals: {trade_counts}")
            await whale_queue.put(filtered_trades)
        validator_queue.task_done()

async def main():
    conn = psycopg2.connect(**db_params)
    app = web.Application()
    app.add_routes([web.post('/trades', handle_trades)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8000)
    await site.start()
    asyncio.create_task(trade_task(validator_queue, whale_queue, conn))
    print("Server running at http://localhost:8000")
    await asyncio.Event().wait()  # Keep running

if __name__ == "__main__":
    asyncio.run(main())
