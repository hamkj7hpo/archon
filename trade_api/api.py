from fastapi import FastAPI, HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
from datetime import datetime, timedelta, timezone
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from contextlib import asynccontextmanager
import pandas as pd
import numpy as np
from decimal import Decimal

app = FastAPI()

# Database Connection Parameters
DB_PARAMS = {
    "dbname": "archon_data",
    "user": "postgres",
    "password": "#!01$Archon$10!#",
    "host": "localhost",
    "port": "5432"
}

# File Paths
TARGET_CONSTANTS_FILE = "/home/safe-pump/archon/target_constants.json"
DOJI_JSON_PATH = "/home/safe-pump/archon/doji.json"
PRICE_JSON_PATH = "/home/safe-pump/archon/raydium/price.json"

# In-memory cache
data_cache = {
    "price": 0.0,
    "buys": 0,
    "sells": 0,
    "holds": 0,
    "classifications": {},
    "whale_trade": None,
    "last_updated": None,
    "token": None,
    "last_trade_time": None,
    "trends": {},
    "doji_signal": None,
    "candle_trend": [],
    "trend_stats": {},
    "trade_trend": []
}

# Database Connection
def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_PARAMS, cursor_factory=RealDictCursor)
        print("🚀 Database connection successful 📊")
        return conn
    except Exception as e:
        print(f"🚨 Database connection failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

# Load Constants
def load_constants():
    try:
        with open(TARGET_CONSTANTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)['target_token']
    except Exception as e:
        print(f"🚨 Failed to load constants: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load constants: {str(e)}")

# Load Doji Data (last 15 minutes)
def load_doji_data():
    try:
        if not os.path.exists(DOJI_JSON_PATH):
            with open(DOJI_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump([], f)
            print(f"📝 Initialized empty {DOJI_JSON_PATH}")
        with open(DOJI_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                print(f"⚠️ Invalid {DOJI_JSON_PATH} format, resetting to empty list")
                with open(DOJI_JSON_PATH, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                return []
        current_time = datetime.now(timezone.utc)
        recent_dojis = [
            d for d in data 
            if (current_time - datetime.strptime(d['timestamp'], "%Y-%m-%d %H:%M:00").replace(tzinfo=timezone.utc)).total_seconds() < 900
        ]
        print(f"🔍 Loaded {len(recent_dojis)} Doji entries from {DOJI_JSON_PATH} (last 15min)")
        return sorted(recent_dojis, key=lambda x: datetime.strptime(x['timestamp'], "%Y-%m-%d %H:%M:00"), reverse=True)
    except json.JSONDecodeError as e:
        print(f"🚨 Failed to load {DOJI_JSON_PATH}: Invalid JSON {str(e)}")
        with open(DOJI_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump([], f)
        return []
    except Exception as e:
        print(f"🚨 Failed to load {DOJI_JSON_PATH}: {str(e)}")
        return []

# Fetch Candlestick Data
def fetch_candlestick_data(token):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:00")
        cur.execute(
            """
            SELECT id, token_pair, timestamp, open, high, low, close, ma_10, ma_50, doji_type
            FROM public.candles
            WHERE token_pair = %s AND timestamp >= %s
            ORDER BY timestamp DESC
            """,
            (f"{token}/USD", query_time)
        )
        candles = cur.fetchall()
        cur.close()
        conn.close()
        print(f"📊 Fetched {len(candles)} candlestick rows for {token}/USD (last 15min, query time >= {query_time})")
        if len(candles) == 0:
            print(f"⚠️ No candles found. Check price.py or database table 'candles'.")

        if not candles:
            return pd.DataFrame(), {}, []

        # Convert to DataFrame
        df = pd.DataFrame(candles)
        # Ensure numeric columns are float, handle None by converting to np.nan
        for col in ['open', 'high', 'low', 'close', 'ma_10', 'ma_50']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(np.nan)
        df['doji_type'] = df['doji_type'].fillna('None')

        # Validate data
        valid_rows = df.dropna(subset=['open', 'high', 'low', 'close'])
        if len(valid_rows) < len(df):
            print(f"⚠️ Dropped {len(df) - len(valid_rows)} rows with invalid numeric values")
            df = valid_rows

        if df.empty:
            print("⚠️ No valid candlestick data after processing")
            return pd.DataFrame(), {}, []

        # Use price.py's doji_type for classification
        df['is_doji'] = df['doji_type'] != 'None'
        df['is_bullish'] = (df['close'] > df['open']) & (~df['is_doji'])
        df['is_bearish'] = (df['close'] < df['open']) & (~df['is_doji'])

        # Calculate trend stats
        bullish_candles = len(df[df['is_bullish']])
        bearish_candles = len(df[df['is_bearish']])
        doji_candles = len(df[df['is_doji']])
        doji_counts = df[df['is_doji']]['doji_type'].value_counts().to_dict()

        trend_stats = {
            "bullish_candles": bullish_candles,
            "bearish_candles": bearish_candles,
            "doji_candles": doji_candles,
            "doji_counts": doji_counts
        }
        print(f"🕯️ 15min trend: {bullish_candles} bullish, {bearish_candles} bearish, {doji_candles} Dojis, counts: {doji_counts}")

        # Prepare raw candles for API response
        raw_candles = []
        for _, row in df.iterrows():
            candle = {
                "id": row['id'],
                "token_pair": row['token_pair'],
                "timestamp": row['timestamp'].strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "ma_10": float(row['ma_10']) if not pd.isna(row['ma_10']) else None,
                "ma_50": float(row['ma_50']) if not pd.isna(row['ma_50']) else None,
                "doji_type": row['doji_type']
            }
            raw_candles.append(candle)

        return df, trend_stats, raw_candles
    except Exception as e:
        print(f"🚨 Error fetching candlestick data: {str(e)}")
        return pd.DataFrame(), {}, []

# Fetch Aggregated Trades (unchanged)
def fetch_recent_trades(token):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 
                DATE_TRUNC('minute', detected_time) as minute,
                trade_type,
                COUNT(*) as count,
                SUM(amount) as total_amount,
                classification
            FROM public.whale_detector
            WHERE token = %s AND detected_time >= %s
            GROUP BY DATE_TRUNC('minute', detected_time), trade_type, classification
            ORDER BY minute DESC
            """,
            (token, datetime.now(timezone.utc) - timedelta(minutes=15))
        )
        trade_results = cur.fetchall()
        print(f"🐳 Fetched {len(trade_results)} aggregated trade rows for token {token}")
        cur.execute(
            """
            SELECT whale_wallet, token, trade_type, classification, amount, detected_time
            FROM public.whale_detector
            WHERE token = %s 
            AND detected_time >= %s
            AND classification IN ('🐋', '🐳', '🦈')
            AND trade_type IN ('buy', 'sell')
            ORDER BY detected_time DESC
            LIMIT 1
            """,
            (token, datetime.now(timezone.utc) - timedelta(minutes=15, seconds=5))
        )
        latest_trade = cur.fetchone()
        print(f"🐳 Latest whale trade query result: {latest_trade}")
        cur.close()
        conn.close()

        buys = 0
        sells = 0
        holds = 0
        classifications = {}
        total_volume = 0.0
        latest_time = None
        trade_trend = []

        if trade_results:
            df_trades = pd.DataFrame(trade_results)
            for minute, group in df_trades.groupby('minute'):
                minute_buys = group[group['trade_type'] == 'buy']['count'].sum()
                minute_sells = group[group['trade_type'] == 'sell']['count'].sum()
                minute_holds = group[group['trade_type'] == 'hold']['count'].sum()
                trade_trend.append({
                    "minute": minute.isoformat(),
                    "buys": int(minute_buys),
                    "sells": int(minute_sells),
                    "holds": int(minute_holds)
                })
            for row in trade_results:
                trade_type = row['trade_type']
                count = row['count']
                cls = row['classification']
                amount = float(row['total_amount']) / 1_000_000_000
                if trade_type == 'buy':
                    buys += count
                    total_volume += amount
                elif trade_type == 'sell':
                    sells += count
                    total_volume += amount
                elif trade_type == 'hold':
                    holds += count
                if cls:
                    classifications[cls] = classifications.get(cls, 0) + count
            print(f"🐳 Processed: {buys} buys, {sells} sells, {holds} holds, volume: {total_volume:.2f} SOL, classifications: {classifications}")

        if latest_trade:
            latest_time = latest_trade['detected_time'].isoformat()
            print(f"🐳 Latest whale trade at {latest_time}")

        return buys, sells, holds, classifications, latest_trade, latest_time, total_volume, trade_trend
    except Exception as e:
        print(f"🚨 Error fetching trades: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching trades: {str(e)}")

# Calculate Sea Life Score (unchanged)
def calculate_sea_life_score(classifications, total_volume):
    SEA_LIFE_WEIGHTS = {
        "🐋": 2.0, "🐳": 1.0, "🦈": 0.5, "🐙": 0.25, "🐬": 0.1, "🦑": 0.05,
        "🐟": 0.01, "🐡": 0.015, "🦭": 0.02, "🦞": 0.01, "🦀": 0.005,
        "🐢": 0.003, "🦐": 0.002, "🐚": 0.001, "🦪": 0.001, "🪸": 0.0005,
        "🐠": 0.0003, "🐌": 0.0001, "🌊": 0.0
    }
    score = sum(SEA_LIFE_WEIGHTS.get(cls, 0) * count for cls, count in classifications.items())
    volume_factor = min(total_volume / 10, 2.0)
    return score * (1 + volume_factor)

# Background Tasks
async def update_price_and_trends():
    constants = load_constants()
    token = constants['ticker']
    candlestick_data, trend_stats, raw_candles = fetch_candlestick_data(token)
    doji_data = load_doji_data()

    if candlestick_data.empty:
        print("⚠️ No candlestick data available, fetching latest price from price.json")
        try:
            with open(PRICE_JSON_PATH, 'r', encoding='utf-8') as f:
                price_data = json.load(f)
                latest_key = max(price_data.keys(), default=None)
                if latest_key and price_data[latest_key]:
                    price = float(price_data[latest_key][-1]['price'])
                else:
                    price = 0.0
        except Exception as e:
            print(f"🚨 Failed to load price from {PRICE_JSON_PATH}: {str(e)}")
            price = 0.0
        data_cache["price"] = price
        data_cache["trends"] = {}
        data_cache["doji_signal"] = None
        data_cache["candle_trend"] = []
        data_cache["trend_stats"] = {}
    else:
        latest_candle = candlestick_data.iloc[0]
        price = float(latest_candle['close'])
        prices = candlestick_data['close'].astype(float).tolist()
        trends = {
            "avg_price_last_10": np.mean(prices) if prices else price,
            "price_volatility": np.std(prices) / np.mean(prices) if len(prices) > 1 else 0.0,
            "is_bullish": bool(latest_candle['close'] > latest_candle['open']),
        }
        data_cache["price"] = price
        data_cache["trends"] = trends
        data_cache["candle_trend"] = raw_candles
        data_cache["trend_stats"] = trend_stats
        data_cache["doji_signal"] = doji_data[0]['doji_type'] if doji_data else None
        if data_cache["doji_signal"]:
            print(f"⭐ Updated Doji signal: {data_cache['doji_signal']}")

    data_cache["last_updated"] = datetime.now(timezone.utc).isoformat()
    data_cache["token"] = token
    print(f"🤑 Price updated: ${data_cache['price']:.8f} at {data_cache['last_updated']} for {token}")

async def update_trades():
    constants = load_constants()
    token = constants['ticker']
    try:
        buys, sells, holds, classifications, whale_trade, latest_time, total_volume, trade_trend = fetch_recent_trades(token)
        data_cache["buys"] = buys
        data_cache["sells"] = sells
        data_cache["holds"] = holds
        data_cache["classifications"] = classifications
        data_cache["whale_trade"] = dict(whale_trade) if whale_trade else None
        data_cache["last_updated"] = datetime.now(timezone.utc).isoformat()
        data_cache["token"] = token
        data_cache["last_trade_time"] = latest_time
        data_cache["sea_life_score"] = calculate_sea_life_score(classifications, total_volume)
        data_cache["trade_trend"] = trade_trend
        print(f"🐳 Trades updated at {data_cache['last_updated']}: {buys} buys, {sells} sells, {holds} holds, score: {data_cache['sea_life_score']:.2f}, activity: {classifications}")
    except Exception as e:
        print(f"🚨 Trade update failed: {str(e)}")

# Lifespan Handler
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(update_price_and_trends, IntervalTrigger(seconds=10))
    scheduler.add_job(update_trades, IntervalTrigger(seconds=5))
    scheduler.start()
    await update_price_and_trends()
    await update_trades()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# Single Endpoint
@app.get("/data")
def get_data():
    constants = load_constants()
    token = constants['ticker']
    
    if data_cache["token"] != token or not data_cache["last_updated"]:
        return {
            "token": token,
            "price": data_cache["price"],
            "buys": 0,
            "sells": 0,
            "holds": 0,
            "classifications": {},
            "sea_life_score": 0.0,
            "whale_trade": None,
            "trends": {},
            "doji_signal": None,
            "candle_trend": [],
            "trend_stats": {
                "bullish_candles": 0,
                "bearish_candles": 0,
                "doji_candles": 0,
                "doji_counts": {}
            },
            "trade_trend": [],
            "timestamp": data_cache["last_updated"] or datetime.now(timezone.utc).isoformat(),
            "last_trade_time": None,
            "message": "No recent data available yet"
        }
    
    whale_trade = data_cache["whale_trade"]
    if whale_trade:
        whale_trade["amount_sol"] = float(whale_trade["amount"]) / 1_000_000_000

    return {
        "token": token,
        "price": data_cache["price"],
        "buys": data_cache["buys"],
        "sells": data_cache["sells"],
        "holds": data_cache["holds"],
        "classifications": data_cache["classifications"],
        "sea_life_score": data_cache["sea_life_score"],
        "whale_trade": whale_trade,
        "trends": data_cache["trends"],
        "doji_signal": data_cache["doji_signal"],
        "candle_trend": data_cache["candle_trend"],
        "trend_stats": data_cache["trend_stats"],
        "trade_trend": data_cache["trade_trend"],
        "timestamp": data_cache["last_updated"],
        "last_trade_time": data_cache["last_trade_time"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
