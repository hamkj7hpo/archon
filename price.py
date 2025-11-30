import os
import subprocess
import json
import time
import requests
import logging
import sys
import pandas as pd
import numpy as np
from decimal import Decimal
from sqlalchemy import create_engine, Column, Integer, String, Numeric, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
import datetime
import backoff
from sqlalchemy.sql import text
import traceback

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Config
GET_PRICE_SCRIPT_PATH = "raydium/get_price.ts"
PRICE_JSON_PATH = "raydium/price.json"
SOL_PRICE_JSON_PATH = "raydium/sol_price.json"
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
UPDATE_INTERVAL = 4  # seconds
DB_HOST = 'localhost'
DB_PORT = '5432'
DB_NAME = 'archon_data'
DB_USER = 'postgres'
DB_PASSWORD = '#!01$Archon$10!#'
PROCESSED_DOJIS_FILE = 'doji.json'
DOJI_THRESHOLD = 0.002  # 0.2% of close price
MIN_PRICES_PER_CANDLE = 2
PRICE_CHANGE_THRESHOLD = 0.005
SOL_USD_CACHE_TIMEOUT = 600  # Cache SOL/USD for 10 minutes
CANDLE_INTERVAL_1M_MINUTES = 1
CANDLE_INTERVAL_1H_MINUTES = 60

# SQLAlchemy setup
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()

# Define SQLAlchemy model for candles table
class Candle(Base):
    __tablename__ = 'candles'
    __table_args__ = {'schema': 'public'}
    id = Column(Integer, primary_key=True)
    token_pair = Column(String(50), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Numeric(16,8), nullable=False)
    high = Column(Numeric(16,8), nullable=False)
    low = Column(Numeric(16,8), nullable=False)
    close = Column(Numeric(16,8), nullable=False)
    ma_10 = Column(Numeric(16,8))
    ma_50 = Column(Numeric(16,8))
    doji_type = Column(String(20), nullable=False, default='None')

# Global variables
last_valid_data = {"ticker": "UNKNOWN", "price": 0.0, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
last_sol_usd = None
last_sol_usd_time = 0
current_candle_key_1m = None
current_candle_key_1h = None
db_connected = False
cached_candlestick_data = pd.DataFrame()

# Test database connection
def test_db_connection():
    global db_connected
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_connected = True
        logging.info("Connected to database successfully")
    except SQLAlchemyError as e:
        db_connected = False
        logging.error(f"Failed to connect to database: {e}\n{traceback.format_exc()}")
        logging.info("Continuing without database operations")

# Initialize price.json
def initialize_price_json():
    try:
        with open(PRICE_JSON_PATH, 'w') as f:
            json.dump({}, f)
        logging.info(f"Initialized {PRICE_JSON_PATH}")
    except Exception as e:
        logging.error(f"Failed to initialize {PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")

# Initialize sol_price.json
def initialize_sol_price_json():
    try:
        with open(SOL_PRICE_JSON_PATH, 'w') as f:
            json.dump({"sol_usd": 0.0, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}, f)
        logging.info(f"Initialized {SOL_PRICE_JSON_PATH}")
    except Exception as e:
        logging.error(f"Failed to initialize {SOL_PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")

# Initialize doji.json
def initialize_doji_json():
    try:
        with open(PROCESSED_DOJIS_FILE, 'w') as f:
            json.dump([], f)
        logging.info(f"Initialized {PROCESSED_DOJIS_FILE}")
    except Exception as e:
        logging.error(f"Failed to initialize {PROCESSED_DOJIS_FILE}: {e}\n{traceback.format_exc()}")

# Load price.json
def load_price_json():
    try:
        if os.path.exists(PRICE_JSON_PATH):
            with open(PRICE_JSON_PATH, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        return {}
    except Exception as e:
        logging.error(f"Failed to load {PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")
        return {}

# Load sol_price.json
def load_sol_price_json():
    try:
        if os.path.exists(SOL_PRICE_JSON_PATH):
            with open(SOL_PRICE_JSON_PATH, 'r') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {"sol_usd": 0.0, "timestamp": ""}
        return {"sol_usd": 0.0, "timestamp": ""}
    except Exception as e:
        logging.error(f"Failed to load {SOL_PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")
        return {"sol_usd": 0.0, "timestamp": ""}

# Save price to price.json
def save_price_to_json(ticker, price_usd, timestamp):
    try:
        price_data = load_price_json()
        candle_key_1m = datetime.datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        candle_key_1m = candle_key_1m.replace(second=0)
        candle_key_1m = candle_key_1m.strftime("%Y-%m-%d %H:%M:00")
        
        if candle_key_1m not in price_data:
            price_data[candle_key_1m] = []
        price_data[candle_key_1m].append({
            "token_pair": f"{ticker}/USD",
            "timestamp": timestamp,
            "price": float(price_usd)
        })
        last_price = last_valid_data.get("price", 0.0)
        if last_price > 0 and abs(price_usd - last_price) / last_price > PRICE_CHANGE_THRESHOLD:
            logging.info(f"Whale alert! Price change: ${last_price:.8f} -> ${price_usd:.8f}")
        
        with open(PRICE_JSON_PATH, 'w') as f:
            json.dump(price_data, f, indent=4)
        logging.debug(f"Saved price: {ticker}, ${price_usd:.8f}, {timestamp}")
        return candle_key_1m
    except Exception as e:
        logging.error(f"Failed to save price to {PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")
        return None

# Save SOL/USD price to sol_price.json
def save_sol_price_to_json(sol_usd, timestamp):
    try:
        sol_price_data = {
            "sol_usd": float(sol_usd),
            "timestamp": timestamp
        }
        with open(SOL_PRICE_JSON_PATH, 'w') as f:
            json.dump(sol_price_data, f, indent=4)
        logging.debug(f"Saved SOL/USD price: ${sol_usd:.2f}, {timestamp}")
    except Exception as e:
        logging.error(f"Failed to save SOL/USD price to {SOL_PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")

# Clean up old price data
def cleanup_price_json():
    try:
        price_data = load_price_json()
        current_time = datetime.datetime.utcnow()
        cutoff = current_time - datetime.timedelta(minutes=CANDLE_INTERVAL_1H_MINUTES * 2)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:00")
        price_data = {k: v for k, v in price_data.items() if k >= cutoff_str}
        with open(PRICE_JSON_PATH, 'w') as f:
            json.dump(price_data, f, indent=4)
        logging.debug(f"Cleaned up {PRICE_JSON_PATH}, kept after {cutoff_str}")
    except Exception as e:
        logging.error(f"Failed to clean up {PRICE_JSON_PATH}: {e}\n{traceback.format_exc()}")

# Load processed Doji candles
def load_processed_dojis():
    try:
        if not os.path.exists(PROCESSED_DOJIS_FILE):
            initialize_doji_json()
        with open(PROCESSED_DOJIS_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except json.JSONDecodeError as e:
        logging.error(f"Failed to load {PROCESSED_DOJIS_FILE}: Invalid JSON {e}\n{traceback.format_exc()}")
        initialize_doji_json()
        return []
    except Exception as e:
        logging.error(f"Failed to load {PROCESSED_DOJIS_FILE}: {e}\n{traceback.format_exc()}")
        return []

# Save processed Doji candles
def save_processed_dojis(processed_dojis):
    try:
        current_time = datetime.datetime.utcnow()
        cutoff = current_time - datetime.timedelta(hours=24)
        processed_dojis = [d for d in processed_dojis if datetime.datetime.strptime(d['timestamp'], "%Y-%m-%d %H:%M:00") >= cutoff]
        
        with open(PROCESSED_DOJIS_FILE, 'w') as f:
            for doji in processed_dojis:
                for key, value in doji.items():
                    if isinstance(value, Decimal):
                        doji[key] = float(value)
            json.dump(processed_dojis, f, indent=4)
        logging.info(f"Saved {len(processed_dojis)} Doji records")
    except Exception as e:
        logging.error(f"Error saving Doji records: {e}\n{traceback.format_exc()}")

# Calculate moving averages from database
def calculate_moving_averages_from_db(token_pair, timestamp, session):
    try:
        query = session.query(Candle).filter(
            Candle.token_pair == token_pair,
            Candle.timestamp <= timestamp
        ).order_by(Candle.timestamp.desc()).limit(50)
        candles = query.all()
        
        if not candles:
            return None, None
        
        close_prices = [float(candle.close) for candle in candles]
        ma_10 = sum(close_prices[:10]) / len(close_prices[:10]) if len(close_prices) >= 10 else None
        ma_50 = sum(close_prices[:50]) / len(close_prices[:50]) if len(close_prices) >= 50 else None
        
        return ma_10, ma_50
    except SQLAlchemyError as e:
        logging.error(f"Error querying candles for MA: {e}\n{traceback.format_exc()}")
        return None, None

# Detect Doji candles
def detect_doji_type(current_candle, previous_candle=None):
    open_price = float(current_candle['open'])
    close_price = float(current_candle['close'])
    high_price = float(current_candle['high'])
    low_price = float(current_candle['low'])
    
    body_size = abs(open_price - close_price)
    range_size = high_price - low_price
    if range_size == 0:
        return 'None'
    
    if (body_size / close_price < DOJI_THRESHOLD and 
        body_size / range_size < 0.1 and
        abs(high_price - max(open_price, close_price)) > body_size and
        abs(min(open_price, close_price) - low_price) > body_size):
        if previous_candle is None:
            return 'Neutral Doji'
        prev_open = float(previous_candle['open'])
        prev_close = float(previous_candle['close'])
        return 'Bull Doji' if prev_close < prev_open else 'Bear Doji' if prev_close > prev_open else 'Neutral Doji'
    return 'None'

# Process and store candlestick for 1-minute and 1-hour intervals
def process_and_store_candlestick(candle_key, interval_minutes):
    if not db_connected:
        logging.warning(f"Database not connected, skipping {candle_key} ({interval_minutes}m)")
        return
    try:
        price_data = load_price_json()
        if candle_key not in price_data or len(price_data[candle_key]) < MIN_PRICES_PER_CANDLE:
            logging.debug(f"Skipping {candle_key} ({interval_minutes}m): insufficient prices ({len(price_data.get(candle_key, []))})")
            return

        prices = [p['price'] for p in price_data[candle_key]]
        token_pair_base = price_data[candle_key][0]['token_pair']
        token_pair = token_pair_base if interval_minutes == 1 else f"{token_pair_base}_1h"
        logging.info(f"Processing {interval_minutes}-min candle for {candle_key}, {len(prices)} prices: {prices}")

        new_candle = {
            'token_pair': token_pair,
            'timestamp': datetime.datetime.strptime(candle_key, "%Y-%m-%d %H:%M:00"),
            'open': prices[0],
            'high': max(prices),
            'low': min(prices),
            'close': prices[-1]
        }
        logging.debug(f"New candle data: {new_candle}")

        # Calculate MAs from database
        ma_10, ma_50 = calculate_moving_averages_from_db(token_pair, new_candle['timestamp'], session)

        # Detect Doji or candle type
        doji_type = 'None'
        global cached_candlestick_data
        cached_candlestick_data = pd.concat([cached_candlestick_data, pd.DataFrame([new_candle])], ignore_index=True)
        current_candle = cached_candlestick_data.iloc[-1]
        previous_candle = cached_candlestick_data.iloc[-2] if len(cached_candlestick_data) >= 2 else None  # Fixed: Use cached_candlestick_data
        doji_type = detect_doji_type(current_candle, previous_candle)

        # Store candle first
        candle = Candle(
            token_pair=new_candle['token_pair'],
            timestamp=new_candle['timestamp'],
            open=float(new_candle['open']),
            high=float(new_candle['high']),
            low=float(new_candle['low']),
            close=float(new_candle['close']),
            ma_10=ma_10,
            ma_50=ma_50,
            doji_type=doji_type
        )
        session.add(candle)
        session.commit()
        logging.info(f"Stored candle for {token_pair} at {candle_key} in database")

        # Determine candle type and print detailed object
        if doji_type != 'None':
            emoji = "⚪"
            candle_type = f"Doji candle ({doji_type})"
        elif current_candle['close'] > current_candle['open']:
            emoji = "🟢"
            candle_type = "Green candle"
        elif current_candle['close'] < current_candle['open']:
            emoji = "🔴"
            candle_type = "Red candle"
        else:
            emoji = "⚪"
            candle_type = "Neutral candle"

        candle_info = (
            f"{emoji} {candle_type} created! "
            f"Token Pair: {token_pair}, "
            f"Timestamp: {candle_key}, "
            f"Open: {new_candle['open']:.8f}, "
            f"High: {new_candle['high']:.8f}, "
            f"Low: {new_candle['low']:.8f}, "
            f"Close: {new_candle['close']:.8f}, "
            f"MA_10: {'None' if ma_10 is None else f'{ma_10:.8f}'}, "
            f"MA_50: {'None' if ma_50 is None else f'{ma_50:.8f}'}, "
            f"Doji Type: {doji_type}"
        )
        logging.info(candle_info)

        # Save Doji to doji.json
        processed_dojis = load_processed_dojis()
        if doji_type != 'None' and candle_key not in [d['timestamp'] for d in processed_dojis]:
            processed_dojis.append({
                'timestamp': candle_key,
                'token_pair': token_pair,
                'doji_type': doji_type,
                'close': float(new_candle['close'])
            })
            save_processed_dojis(processed_dojis)

        # Verify insertion
        result = session.query(Candle).filter_by(token_pair=token_pair, timestamp=new_candle['timestamp']).first()
        if result:
            logging.debug(f"Verified candle in database: {result.__dict__}")
        else:
            logging.error(f"Failed to verify candle in database for {token_pair} at {candle_key}")

        if interval_minutes == 1:
            del price_data[candle_key]
            with open(PRICE_JSON_PATH, 'w') as f:
                json.dump(price_data, f, indent=4)
            logging.debug(f"Removed {candle_key} from {PRICE_JSON_PATH}")
    except SQLAlchemyError as e:
        session.rollback()
        logging.error(f"Error storing candle for {candle_key} ({interval_minutes}m): {e}\n{traceback.format_exc()}")
    except Exception as e:
        logging.error(f"Unexpected error for {candle_key} ({interval_minutes}m): {e}\n{traceback.format_exc()}")

# Aggregate 1-minute candles into 1-hour candles
def aggregate_1h_candles():
    try:
        price_data = load_price_json()
        current_time = datetime.datetime.utcnow()
        cutoff = current_time - datetime.timedelta(minutes=CANDLE_INTERVAL_1H_MINUTES)
        candle_keys_1m = sorted([k for k in price_data.keys() if datetime.datetime.strptime(k, "%Y-%m-%d %H:%M:00") <= cutoff])
        
        if not candle_keys_1m:
            return None

        prices_1h = []
        token_pair_base = None
        for key in candle_keys_1m:
            if price_data[key]:
                token_pair_base = price_data[key][0]['token_pair']
                prices_1h.extend([p['price'] for p in price_data[key]])
        
        if not prices_1h or not token_pair_base:
            return None

        candle_key_1h = current_time.replace(minute=0, second=0).strftime("%Y-%m-%d %H:00:00")
        token_pair_1h = f"{token_pair_base}_1h"

        new_candle = {
            'token_pair': token_pair_1h,
            'timestamp': datetime.datetime.strptime(candle_key_1h, "%Y-%m-%d %H:00:00"),
            'open': prices_1h[0],
            'high': max(prices_1h),
            'low': min(prices_1h),
            'close': prices_1h[-1]
        }

        # Calculate MAs from database
        ma_10, ma_50 = calculate_moving_averages_from_db(token_pair_1h, new_candle['timestamp'], session)

        global cached_candlestick_data
        cached_candlestick_data = pd.concat([cached_candlestick_data, pd.DataFrame([new_candle])], ignore_index=True)
        
        doji_type = 'None'
        current_candle = cached_candlestick_data.iloc[-1]
        previous_candle = cached_candlestick_data.iloc[-2] if len(cached_candlestick_data) >= 2 else None
        doji_type = detect_doji_type(current_candle, previous_candle)

        # Store candle first
        candle = Candle(
            token_pair=new_candle['token_pair'],
            timestamp=new_candle['timestamp'],
            open=float(new_candle['open']),
            high=float(new_candle['high']),
            low=float(new_candle['low']),
            close=float(new_candle['close']),
            ma_10=ma_10,
            ma_50=ma_50,
            doji_type=doji_type
        )
        session.add(candle)
        session.commit()
        logging.info(f"Stored 1-hour candle for {token_pair_1h} at {candle_key_1h}")

        # Determine candle type and print detailed object
        if doji_type != 'None':
            emoji = "⚪"
            candle_type = f"Doji candle ({doji_type})"
        elif current_candle['close'] > current_candle['open']:
            emoji = "🟢"
            candle_type = "Green candle"
        elif current_candle['close'] < current_candle['open']:
            emoji = "🔴"
            candle_type = "Red candle"
        else:
            emoji = "⚪"
            candle_type = "Neutral candle"

        candle_info = (
            f"{emoji} {candle_type} created! "
            f"Token Pair: {token_pair_1h}, "
            f"Timestamp: {candle_key_1h}, "
            f"Open: {new_candle['open']:.8f}, "
            f"High: {new_candle['high']:.8f}, "
            f"Low: {new_candle['low']:.8f}, "
            f"Close: {new_candle['close']:.8f}, "
            f"MA_10: {'None' if ma_10 is None else f'{ma_10:.8f}'}, "
            f"MA_50: {'None' if ma_50 is None else f'{ma_50:.8f}'}, "
            f"Doji Type: {doji_type}"
        )
        logging.info(candle_info)

        processed_dojis = load_processed_dojis()
        if doji_type != 'None' and candle_key_1h not in [d['timestamp'] for d in processed_dojis]:
            processed_dojis.append({
                'timestamp': candle_key_1h,
                'token_pair': token_pair_1h,
                'doji_type': doji_type,
                'close': float(new_candle['close'])
            })
            save_processed_dojis(processed_dojis)

        return candle_key_1h
    except SQLAlchemyError as e:
        session.rollback()
        logging.error(f"Error aggregating 1-hour candle: {e}\n{traceback.format_exc()}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error aggregating 1-hour candle: {e}\n{traceback.format_exc()}")
        return None

# Load last valid price
def load_last_valid_price():
    global last_valid_data
    try:
        price_data = load_price_json()
        for minute, prices in sorted(price_data.items(), reverse=True):
            if prices and isinstance(prices, list) and prices[0].get("price", 0.0) > 0:
                last_valid_data = {
                    "ticker": prices[0]["token_pair"].split("/")[0],
                    "price": prices[0]["price"],
                    "timestamp": prices[0]["timestamp"]
                }
                logging.info(f"Loaded last valid price: ${last_valid_data['price']:.8f} for {last_valid_data['ticker']}")
                break
    except Exception as e:
        logging.error(f"Failed to load last valid price: {e}\n{traceback.format_exc()}")

# Fetch SOL/USD price
@backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=5, max_time=120)
def get_sol_usd_price():
    global last_sol_usd, last_sol_usd_time
    current_time = time.time()
    if last_sol_usd is not None and current_time - last_sol_usd_time < SOL_USD_CACHE_TIMEOUT:
        return last_sol_usd

    try:
        response = requests.get(COINGECKO_API)
        response.raise_for_status()
        sol_usd = response.json()["solana"]["usd"]
        last_sol_usd = sol_usd
        last_sol_usd_time = current_time
        save_sol_price_to_json(sol_usd, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
        logging.info(f"Fetched and saved SOL/USD price: ${sol_usd}")
        return sol_usd
    except requests.exceptions.RequestException as e:
        logging.error(f"CoinGecko failed: {e}\n{traceback.format_exc()}")
        if last_sol_usd is not None:
            logging.info(f"Using cached SOL/USD price: ${last_sol_usd}")
            return last_sol_usd
        raise Exception("No cached SOL/USD price available")

# Fetch token price in USD
def get_price_in_usd():
    try:
        result = subprocess.run(
            ["ts-node", GET_PRICE_SCRIPT_PATH],
            capture_output=True,
            text=True,
            check=True
        )
        price_data = json.loads(result.stdout.strip())
        ticker = price_data["ticker"]
        token_price_in_sol = 1 / price_data["priceInSol"] if price_data["priceInSol"] > 0 else 0
        sol_usd = get_sol_usd_price()
        token_price_in_usd = token_price_in_sol * sol_usd
        logging.info(f"Price: {ticker} = {token_price_in_sol:.8f} SOL, ${token_price_in_usd:.8f} USD")
        return ticker, token_price_in_usd
    except subprocess.CalledProcessError as e:
        logging.error(f"Raydium price fetch failed: {e.stderr}\n{traceback.format_exc()}")
        return None, None
    except Exception as e:
        logging.error(f"Price fetch error: {e}\n{traceback.format_exc()}")
        return None, None

# Main loop
def save_price_and_process_candlesticks():
    global current_candle_key_1m, current_candle_key_1h
    logging.info("Starting price fetcher for 1-min and 1-hour candles")
    initialize_price_json()
    initialize_sol_price_json()
    initialize_doji_json()
    load_last_valid_price()
    test_db_connection()

    while True:
        try:
            ticker, price_usd = get_price_in_usd()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            if ticker and price_usd and price_usd > 0:
                candle_key_1m = save_price_to_json(ticker, price_usd, timestamp)
                if candle_key_1m:
                    new_candle_key_1m = datetime.datetime.utcnow().replace(second=0).strftime("%Y-%m-%d %H:%M:00")
                    new_candle_key_1h = datetime.datetime.utcnow().replace(minute=0, second=0).strftime("%Y-%m-%d %H:00:00")
                    
                    if current_candle_key_1m and current_candle_key_1m != new_candle_key_1m:
                        logging.info(f"New 1-min candle: {new_candle_key_1m}. Processing {current_candle_key_1m}")
                        process_and_store_candlestick(current_candle_key_1m, CANDLE_INTERVAL_1M_MINUTES)
                    
                    if current_candle_key_1h and current_candle_key_1h != new_candle_key_1h:
                        logging.info(f"New 1-hour candle: {new_candle_key_1h}. Aggregating 1-min candles")
                        aggregate_1h_candles()
                    
                    current_candle_key_1m = new_candle_key_1m
                    current_candle_key_1h = new_candle_key_1h
                cleanup_price_json()
            else:
                logging.warning(f"Invalid price data: ticker={ticker}, price={price_usd}")
            time.sleep(UPDATE_INTERVAL)
        except Exception as e:
            logging.error(f"Error in main loop: {e}\n{traceback.format_exc()}")
            time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    try:
        Base.metadata.create_all(engine)
        save_price_and_process_candlesticks()
    except KeyboardInterrupt:
        logging.info("Stopped by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        sys.exit(1)
