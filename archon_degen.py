import os
import time
import logging
import subprocess
import json
import sys
import random
import shutil
import requests
from datetime import datetime, timedelta, timezone
import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
from pyfiglet import Figlet
from termcolor import colored
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from tenacity import retry, stop_after_attempt, wait_fixed, wait_exponential, retry_if_exception_type

# Config
POLICY_PATH = "/home/safe-pump/archon/mev/data/archon.pth"
STATE_FILE = "/home/safe-pump/archon/archon_degen_state.json"
OUTPUT_FILE = "/home/safe-pump/archon/output.json"
CONSTANTS_FILE = "/home/safe-pump/archon/target_constants.json"
RPC_ENDPOINT = "https://mainnet.helius-rpc.com/?api-key=479f2b3d-a5e4-4fa0-b7ac-163dc4b14133"
WALLET_KEYPAIR_PATH = "/home/safe-pump/archon/wallet.json"
SWAP_SCRIPT_PATH = "/home/safe-pump/archon/raydium/raydium_swap.ts"
UPDATE_INTERVAL = 2.0
SELL_COOLDOWN = 15.0
BUY_COOLDOWN = 15.0
MIN_SWAP_SOL = 0.005
FEE_PER_TRADE = 0.002
NETWORK_FEE = 0.000005
API_URL = "http://127.0.0.1:8000/data"
SNIPER_PERCENTAGE = 0.67
MIN_LIQUID_RESERVE = 0.0075
PROFIT_THRESHOLD = 0.015
TOKEN_SELL_THRESHOLD = 10.0
SLIPPAGE_FACTOR = 0.005
LATENCY_MIN = 0.05
LATENCY_MAX = 0.2
MIN_SOL_FOR_TRADE = 0.003
SKIP_SNIPE = False
DUMP_ON_BOOT = False
TRADE_CONFIRMATION_DELAY = 2.0
STOP_LOSS_THRESHOLD = -0.10
FORCE_TRADE_INTERVAL = 300.0
TREND_WINDOW = 300
MOVING_AVERAGE_PERIOD = 10
MINIMUM_SOL_REQUIRED = MIN_SOL_FOR_TRADE
TREND_DURATION = TREND_WINDOW

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def color(text, color_name, bold=False):
    attrs = ['bold'] if bold else []
    return colored(text, color_name, attrs=attrs)

class SolanaClientManager:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.client = Client(self.endpoint)
        logging.info(f"😺 Initialized Solana client with RPC: {self.endpoint}")

    def get_client(self):
        return self.client

    def get_current_endpoint(self):
        return self.endpoint

solana_client_manager = SolanaClientManager(RPC_ENDPOINT)

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname="archon_data",
            user="postgres",
            password=os.getenv("PG_PASSWORD", "#!01$Archon$10!#"),
            host="localhost",
            port="5432"
        )
        logging.debug("🗄️ Database connection established")
        return conn
    except Exception as e:
        logging.error(f"🚨 Failed to connect to database: {e}")
        return None

def load_wallet():
    with open(WALLET_KEYPAIR_PATH, 'r') as f:
        keypair_data = json.load(f)
    return Keypair.from_seed(bytes(keypair_data[:32]))

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(Exception)
)
def get_sol_balance(wallet: Keypair):
    client = solana_client_manager.get_client()
    try:
        balance = client.get_balance(wallet.pubkey()).value / 1_000_000_000
        logging.info(f"💰 Fetched SOL balance: {balance} using {solana_client_manager.get_current_endpoint()}")
        return balance
    except Exception as e:
        logging.error(f"🚨 Failed to fetch SOL balance: {e}")
        raise

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(Exception)
)
def get_token_balance(wallet: Keypair, token_mint: Pubkey):
    client = solana_client_manager.get_client()
    try:
        opts = TokenAccountOpts(mint=token_mint, encoding="base64")
        response = client.get_token_accounts_by_owner(wallet.pubkey(), opts)
        if hasattr(response, 'value') and response.value and len(response.value) > 0:
            token_account = response.value[0].pubkey
            balance_response = client.get_token_account_balance(token_account, commitment="confirmed")
            if hasattr(balance_response, 'value') and balance_response.value.ui_amount is not None:
                balance = balance_response.value.ui_amount
                logging.info(f"💰 Fetched token balance for mint {token_mint}: {balance} 🐱")
                return balance
            return 0.0
        return 0.0
    except Exception as e:
        logging.error(f"🚨 Failed to fetch token balance: {e}")
        raise

class TradeTracker:
    def __init__(self, max_sol, state=None):
        self.max_sol = max_sol
        self.sol_liquid_available = state.get("tracker_state", {}).get("sol_liquid_available", max_sol - MIN_LIQUID_RESERVE)
        self.sol_trimmed = state.get("tracker_state", {}).get("sol_trimmed", 0.0)
        self.avg_buy_price = state.get("tracker_state", {}).get("avg_buy_price", 0.0)
        self.current_roll = state.get("tracker_state", {}).get("current_roll", 0.0)
        self.token_amount = state.get("tracker_state", {}).get("token_amount", 0.0)
        self.last_sell_attempt = state.get("tracker_state", {}).get("last_sell_attempt", 0.0)
        self.last_buy_attempt = state.get("tracker_state", {}).get("last_buy_attempt", 0.0)
        self.last_trade_time = state.get("tracker_state", {}).get("last_trade_time", time.time())
        self.buy_history = state.get("tracker_state", {}).get("buy_history", [])
        self.price_history = state.get("tracker_state", {}).get("price_history", [])

    def update_buy(self, sol_spent, token_bought, price, txid):
        if sol_spent > self.sol_liquid_available:
            sol_spent = self.sol_liquid_available
        self.current_roll += sol_spent
        self.token_amount += token_bought
        self.buy_history.append({
            "sol_spent": sol_spent,
            "token_bought": token_bought,
            "price": price,
            "timestamp": time.time(),
            "txid": txid or "pending"
        })
        total_tokens = sum(b["token_bought"] for b in self.buy_history)
        self.avg_buy_price = sum(b["token_bought"] * b["price"] for b in self.buy_history) / total_tokens if total_tokens > 0 else price
        self.sol_liquid_available -= sol_spent
        self.last_trade_time = time.time()
        self.last_buy_attempt = time.time()
        self.price_history.append({"price": price, "timestamp": time.time()})
        self.price_history = [p for p in self.price_history if time.time() - p["timestamp"] < TREND_WINDOW]
        logging.debug(f"🤑 Buy update: Liquid={self.sol_liquid_available:.6f}, Trimmed={self.sol_trimmed:.6f}, Tokens={self.token_amount:.2f}, Avg Buy Price=${self.avg_buy_price:.8f}, Current Roll={self.current_roll:.6f}")

    def update_sell(self, sol_received, token_sold, price, txid):
        if token_sold > self.token_amount:
            token_sold = self.token_amount
        self.sol_liquid_available += sol_received
        trim_amount = sol_received * 0.35
        self.sol_liquid_available -= trim_amount
        self.sol_trimmed += trim_amount
        self.token_amount -= token_sold
        self.buy_history.append({
            "sol_spent": -sol_received,
            "token_bought": -token_sold,
            "price": price,
            "timestamp": time.time(),
            "txid": txid or "pending"
        })
        if self.token_amount <= 0:
            self.token_amount = 0
            self.current_roll = 0
            self.avg_buy_price = 0.0
            self.buy_history = []
        self.last_trade_time = time.time()
        self.last_sell_attempt = time.time()
        self.price_history.append({"price": price, "timestamp": time.time()})
        self.price_history = [p for p in self.price_history if time.time() - p["timestamp"] < TREND_WINDOW]
        logging.debug(f"🤑 Sell update: Liquid={self.sol_liquid_available:.6f}, Trimmed={self.sol_trimmed:.6f}, Tokens={self.token_amount:.2f}")

    def sync_with_wallet(self, wallet_balance, token_balance, force_sync=False):
        current_time = time.time()
        if wallet_balance is not None:
            total_tracked = self.sol_liquid_available + self.sol_trimmed
            if force_sync or abs(total_tracked - wallet_balance) > NETWORK_FEE * 2:
                trim_ratio = self.sol_trimmed / total_tracked if total_tracked > 0 else 0.5
                if current_time - self.last_trade_time > TRADE_CONFIRMATION_DELAY or force_sync:
                    new_total_sol = wallet_balance
                    self.sol_trimmed = min(self.sol_trimmed, new_total_sol * trim_ratio)
                    self.sol_liquid_available = new_total_sol - self.sol_trimmed
                    logging.info(f"🎯 Synced SOL with wallet: Liquid={self.sol_liquid_available:.6f}, Trimmed={self.sol_trimmed:.6f}, Total={wallet_balance:.6f}")
        
        if token_balance is not None:
            if force_sync or abs(token_balance - self.token_amount) > 0.001:
                self.token_amount = token_balance
                if token_balance == 0:
                    self.current_roll = 0
                    self.avg_buy_price = 0.0
                    self.buy_history = []
                    logging.info(f"🎯 Reset token state: No tokens in wallet, cleared buy history")
                elif token_balance > self.token_amount and not self.buy_history:
                    self.buy_history.append({
                        "sol_spent": 0.022196,
                        "token_bought": token_balance,
                        "price": 0.03027745,
                        "timestamp": current_time,
                        "txid": "unknown"
                    })
                    self.current_roll = 0.022196
                    self.avg_buy_price = 0.03027745
                    logging.info(f"🎯 Reconstructed buy history: {token_balance:.2f} tokens @ ${self.avg_buy_price:.8f}")
                logging.debug(f"🎯 Synced token amount: {self.token_amount:.2f}")

    def save_to_state(self, state):
        total_sol = self.sol_liquid_available + self.sol_trimmed
        state["profit_loss"] = total_sol - state.get("initial_sol_balance", self.max_sol)
        state["tracker_state"] = {
            "sol_liquid_available": self.sol_liquid_available,
            "sol_trimmed": self.sol_trimmed,
            "avg_buy_price": self.avg_buy_price,
            "current_roll": self.current_roll,
            "token_amount": self.token_amount,
            "last_sell_attempt": self.last_sell_attempt,
            "last_buy_attempt": self.last_buy_attempt,
            "last_trade_time": self.last_trade_time,
            "buy_history": self.buy_history,
            "price_history": self.price_history
        }

def load_constants():
    try:
        with open(CONSTANTS_FILE, 'r') as f:
            constants = json.load(f)
        ticker = constants["target_token"]["ticker"]
        mint = Pubkey.from_string(constants["target_token"]["mint_address"])
        return {"ticker": ticker, "mint": mint}
    except Exception as e:
        logging.error(f"🚨 Failed to load constants: {e}")
        return {"ticker": "JELLY", "mint": Pubkey.from_string("FeR8VBqNRSUD5NtXAj2n3j1dAHkZHfyDktKuLXD4pump")}

def load_state():
    state_file = STATE_FILE
    default_state = {
        "cached_sol_balance": 0.0,
        "cached_token_balance": 0.0,
        "trade_history": [],
        "profit_loss": 0.0,
        "initial_snipe_done": False,
        "tracker_state": {
            "sol_liquid_available": 0.0,
            "sol_trimmed": 0.0,
            "avg_buy_price": 0.0,
            "current_roll": 0.0,
            "token_amount": 0.0,
            "last_sell_attempt": 0.0,
            "last_buy_attempt": 0.0,
            "last_trade_time": time.time(),
            "buy_history": [],
            "price_history": []
        },
        "market_trends": {
            "avg_price_last_10": 0.0,
            "price_volatility": 0.0,
            "avg_sea_life_score": 0.0,
            "buy_success_rate": 0.0,
            "sell_profit_rate": 0.0
        },
        "last_forced_trade_time": 0.0,
        "flip_count": 0,
        "cycle_start_time": time.time(),
        "last_cycle_pl": 0.0,
        "last_price_update": time.time()
    }
    try:
        if not os.path.exists(state_file) or os.path.getsize(state_file) == 0:
            logging.info(f"📝 Initializing new state at {state_file}")
            save_state(default_state)
            return default_state
        with open(state_file, "r") as f:
            state = json.load(f)
            if not isinstance(state, dict):
                logging.warning(f"⚠️ Invalid state file content, resetting to default")
                save_state(default_state)
                return default_state
            state.setdefault("tracker_state", default_state["tracker_state"])
            state.setdefault("market_trends", default_state["market_trends"])
            state.setdefault("last_forced_trade_time", default_state["last_forced_trade_time"])
            state.setdefault("flip_count", default_state["flip_count"])
            state.setdefault("cycle_start_time", default_state["cycle_start_time"])
            state.setdefault("last_cycle_pl", default_state["last_cycle_pl"])
            state.setdefault("last_price_update", default_state["last_price_update"])
            logging.info(f"📝 Loaded state from {state_file}")
            return state
    except Exception as e:
        logging.error(f"🚨 Failed to load state: {e}, resetting to default")
        save_state(default_state)
        return default_state

def save_state(state):
    try:
        with open(STATE_FILE + '.tmp', 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(STATE_FILE + '.tmp', STATE_FILE)
        logging.debug(f"💾 State saved to {STATE_FILE}")
    except Exception as e:
        logging.error(f"🚨 Failed to save state: {e}")

def log_trade(trade):
    trade_log_file = "/home/safe-pump/archon/trade_log.json"
    try:
        trades = []
        if os.path.exists(trade_log_file):
            with open(trade_log_file, "r") as f:
                trades = json.load(f)
        trades.append(trade)
        with open(trade_log_file, "w") as f:
            json.dump(trades, f, indent=2)
    except Exception as e:
        logging.error(f"🚨 Failed to log trade: {e}")

def fetch_data():
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"Raw candle_trend from API: {data.get('candle_trend')}")
        if not isinstance(data.get("candle_trend"), list) or not all(isinstance(c, dict) for c in data.get("candle_trend", [])):
            logging.warning("⚠️ Invalid candle_trend in API data, fetching from database")
            conn = get_db_connection()
            candles = []
            if conn:
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT open, high, low, close, ma_10, ma_50, doji_type
                            FROM candles
                            WHERE token_pair = %s
                            AND timestamp >= %s
                            ORDER BY timestamp DESC
                            LIMIT 15
                        """, ("JELLY/USD", (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:00")))
                        candles = cur.fetchall()
                        logging.debug(f"Fetched {len(candles)} candles directly from database")
                except Exception as e:
                    logging.error(f"🚨 Failed to fetch candles from database: {e}")
                finally:
                    conn.close()
            data["candle_trend"] = [
                {
                    "open": float(c['open']),
                    "high": float(c['high']),
                    "low": float(c['low']),
                    "close": float(c['close']),
                    "ma_10": float(c['ma_10']) if c['ma_10'] is not None else None,
                    "ma_50": float(c['ma_50']) if c['ma_50'] is not None else None,
                    "doji_type": c['doji_type']
                } for c in candles
            ] if candles else [{"open": 0.0310, "high": 0.0312, "low": 0.0308, "close": 0.0311, "ma_10": 0.0310, "ma_50": 0.0309, "doji_type": "None"}]
        logging.info(f"🤑 Fetched API data: price=${data.get('price', 0.03066045):.8f}, doji={data.get('doji_signal')}, score={data.get('sea_life_score', 0.0):.2f}, buys={data.get('buys', 0)}, sells={data.get('sells', 0)} 🐳")
        return data
    except Exception as e:
        logging.error(f"🚨 Failed to fetch API data: {e}")
        return {
            "price": 0.03066045,
            "buys": 0,
            "sells": 0,
            "holds": 0,
            "classifications": {},
            "trends": {},
            "doji_signal": None,
            "sea_life_score": 0.0,
            "candle_trend": [{"open": 0.0310, "high": 0.0312, "low": 0.0308, "close": 0.0311, "ma_10": 0.0310, "ma_50": 0.0309, "doji_type": "None"}],
            "trade_trend": []
        }

def calculate_sea_life_score(classifications):
    SEA_LIFE_WEIGHTS = {
        "🐳": 0.5, "🦈": 0.3, "🐬": 0.1, "🐟": 0.01, "🐙": 0.05, "🦑": 0.03, "🦐": 0.005, "🦭": 0.02, "🐡": 0.015, "🦞": 0.01
    }
    return sum(SEA_LIFE_WEIGHTS.get(creature, 0) * count for creature, count in classifications.items())

def calculate_moving_averages(classifications):
    try:
        if not classifications:
            logging.debug("No classifications provided, fetching from whale_detector")
            conn = get_db_connection()
            if conn:
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                            SELECT classification, COUNT(*) as count
                            FROM whale_detector
                            WHERE token = %s AND detected_time >= %s
                            GROUP BY classification
                        """, ('JELLY', (datetime.utcnow() - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:00")))
                        classifications = {row['classification']: row['count'] for row in cur.fetchall()}
                except Exception as e:
                    logging.error(f"🚨 Failed to fetch classifications from whale_detector: {e}")
                    classifications = {}
                finally:
                    conn.close()
        score = calculate_sea_life_score(classifications)
        logging.debug(f"Calculated moving averages score: {score:.2f} from classifications: {classifications}")
        return score
    except Exception as e:
        logging.error(f"🚨 Error in calculate_moving_averages: {e}")
        return 0.0

def update_state_after_trade(state, action, amount, sol_amount, price, txid, sea_life_score, profit=0.0, avg_buy_price=0.0, exit_target=0.0):
    trade = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "amount": amount,
        "sol_amount": sol_amount,
        "price": price,
        "txid": txid,
        "sea_life_score": sea_life_score,
        "profit": profit,
        "avg_buy_price": avg_buy_price,
        "exit_target": exit_target
    }
    state["trade_history"].append(trade)
    log_trade(trade)
    if len(state["trade_history"]) > 60:
        state["trade_history"] = state["trade_history"][-50:]
    
    recent_trades = state["trade_history"][-10:]
    prices = [t["price"] for t in recent_trades]
    state["market_trends"]["avg_price_last_10"] = sum(prices) / len(prices) if prices else 0.0
    state["market_trends"]["price_volatility"] = min((max(prices) - min(prices)) / state["market_trends"]["avg_price_last_10"], 0.05) if len(prices) > 1 and state["market_trends"]["avg_price_last_10"] > 0 else 0.0
    state["market_trends"]["avg_sea_life_score"] = sum(t["sea_life_score"] for t in recent_trades) / len(recent_trades) if recent_trades else 0.0
    state["market_trends"]["buy_success_rate"] = len([t for t in state["trade_history"] if t["action"] == "BUY" and t["txid"]]) / len([t for t in state["trade_history"] if t["action"] == "BUY"]) if any(t["action"] == "BUY" for t in state["trade_history"]) else 1.0
    state["market_trends"]["sell_profit_rate"] = len([t for t in state["trade_history"] if t["action"] == "SELL" and t["profit"] > 0]) / len([t for t in state["trade_history"] if t["action"] == "SELL"]) if any(t["action"] == "SELL" for t in state["trade_history"]) else 1.0
    logging.info(f"📊 Updated market trends: {state['market_trends']}")

def welcome_screen(ticker, initial_sol):
    terminal_width = shutil.get_terminal_size().columns
    fig = Figlet(font='slant')
    ascii_art = fig.renderText("ARCHON V2")
    lines = ascii_art.split('\n')
    if len(lines) > 0:
        lines[0] = "      " + lines[0]
    colored_art = color('\n'.join(lines), 'cyan', bold=True)
    centered_lines = [line.center(terminal_width) for line in colored_art.split('\n') if line.strip()]
    print('\n'.join(centered_lines))
    print(color(f"Target: {ticker} 🖤", 'yellow', bold=True).center(terminal_width))
    print(color("=== Real Trades, Pure Chaos ===", 'magenta', bold=True).center(terminal_width))
    print(color(f"Sniper Mode Engaged: Initial Snipe = {min(initial_sol * SNIPER_PERCENTAGE, initial_sol):,.2f} SOL", 'green').center(terminal_width))
    print(color(f"SOL Liquid Available: {initial_sol:,.2f}", 'green').center(terminal_width))
    print()
    bar_width = min(75, terminal_width - 10)
    print(color("Loading ARCHON V3...", 'white', bold=True).center(terminal_width))
    for i in range(21):
        percent = (i / 20) * 100
        filled = int(bar_width * i / 20)
        bar = '█' * filled + '-' * (bar_width - filled)
        bar_text = f"[{bar}] {percent:.1f}%"
        sys.stdout.write(f"\r{color(bar_text, 'green')}".center(terminal_width))
        sys.stdout.flush()
        time.sleep(0.15)
    print("\n")

def calculate_dynamic_slippage(trends, default_slippage=SLIPPAGE_FACTOR):
    volatility = trends.get("price_volatility", 0.0)
    return min(default_slippage * (1 + volatility * 2), 0.02)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception)
)
def execute_raydium_swap(amount: float, is_buy: bool, ticker: str, fallback_price: float, wallet: Keypair, token_mint: Pubkey, state: dict, tracker: TradeTracker) -> tuple[str, float]:
    max_attempts = 3
    sol_before = state["cached_sol_balance"]
    token_before = tracker.token_amount
    
    for attempt in range(max_attempts):
        slippage = calculate_dynamic_slippage(state.get("market_trends", {})) * (1 + attempt * 0.2)
        logging.debug(f"🔄 Swap attempt {attempt + 1}/{max_attempts}, Slippage: {slippage:.6f}")
        try:
            is_buy_str = "1" if is_buy else "0"
            token_mint_str = str(token_mint)
            result = subprocess.run(
                ["ts-node", SWAP_SCRIPT_PATH, "swap", str(amount), is_buy_str, token_mint_str, str(slippage)],
                capture_output=True,
                text=True
            )
            stdout_lines = result.stdout.strip().split('\n')
            logging.debug(f"Swap stdout: {result.stdout}")
            if result.stderr:
                logging.debug(f"Swap stderr: {result.stderr}")
                if "429" in result.stderr or "Too Many Requests" in result.stderr:
                    raise Exception("RPC rate limit, retrying")
                if "Endpoint URL must start with" in result.stderr:
                    raise ValueError("Invalid RPC endpoint")

            if result.returncode != 0:
                logging.error(f"🚨 Swap failed: {result.stderr}")
                raise Exception("Swap script failed")

            txid = None
            for line in stdout_lines:
                if "Transaction ID:" in line:
                    txid = line.split("Transaction ID:")[1].strip()
                    break

            pool_data_line = next((line for line in stdout_lines if "Pool info:" in line), "Pool info: {}")
            pool_data = json.loads(pool_data_line.split("Pool info:")[1].strip())
            price = pool_data.get("price", fallback_price)
            if price <= 0:
                price = fallback_price

            expected_amount_out = (amount / price) * (1 - FEE_PER_TRADE) - NETWORK_FEE if is_buy else (amount * price) * (1 - FEE_PER_TRADE) - NETWORK_FEE
            time.sleep(TRADE_CONFIRMATION_DELAY)
            sol_after = get_sol_balance(wallet) or sol_before
            token_after = get_token_balance(wallet, token_mint) or token_before
            actual_amount_out = (token_after - token_before) if is_buy else (sol_after - sol_before)
            state["cached_sol_balance"] = sol_after
            state["cached_token_balance"] = token_after
            
            if actual_amount_out > 0 or (not is_buy and token_after == 0 and sol_after > sol_before):
                if is_buy:
                    tracker.update_buy(amount, actual_amount_out, price, txid)
                else:
                    actual_amount_out = sol_after - sol_before
                    tracker.update_sell(actual_amount_out, amount, price, txid)
                logging.info(f"🖋️ Swap executed: TXID={txid or 'unknown'}, Amount={amount:.2f}, Price={price:.8f}, Expected Out={expected_amount_out:.6f}, Actual={actual_amount_out:.6f}")
                tracker.save_to_state(state)
                save_state(state)
                return txid, actual_amount_out
            logging.warning(f"⚠️ Swap attempt {attempt + 1} failed: Amount Out={actual_amount_out:.2f}")
        except Exception as e:
            logging.error(f"🚨 Swap attempt {attempt + 1} error: {str(e)}")
        time.sleep(1)
    
    logging.error(f"🚨 All swap attempts failed for {amount:.2f} {'BUY' if is_buy else 'SELL'}")
    return "", 0.0

def execute_buy_swap(amount: float, is_buy: bool, ticker: str, fallback_price: float, wallet: Keypair, token_mint: Pubkey, state: dict, tracker: TradeTracker) -> tuple[str, float]:
    return execute_raydium_swap(amount, is_buy, ticker, fallback_price, wallet, token_mint, state, tracker)

def execute_sell_swap(amount: float, is_buy: bool, ticker: str, fallback_price: float, wallet: Keypair, token_mint: Pubkey, state: dict, tracker: TradeTracker) -> tuple[str, float]:
    return execute_raydium_swap(amount, is_buy, ticker, fallback_price, wallet, token_mint, state, tracker)

def print_balances(tracker: TradeTracker, ticker: str, last_price: float, state: dict):
    pl = state["profit_loss"]
    print(color(f"SOL Liquid Available: {tracker.sol_liquid_available:.6f}", 'green'))
    print(color(f"SOL Trimmed: {tracker.sol_trimmed:.6f}", 'green'))
    print(color(f"Profit/Loss: {pl:.6f} SOL", 'green' if pl >= 0 else 'red'))
    print(color(f"Total {ticker} Accumulated: {tracker.token_amount:.2f}", 'yellow'))
    print(color(f"Last {ticker} Price: ${last_price:.6f}", 'yellow'))

def parse_trade_trend_time(minute):
    try:
        if isinstance(minute, (int, float)):
            return datetime.fromtimestamp(minute)
        return datetime.fromisoformat(minute.replace('Z', '+00:00'))
    except Exception as e:
        logging.warning(f"Failed to parse trade_trend timestamp {minute}: {e}")
        return datetime.now(timezone.utc)

def get_recent_trades(trade_trend, current_time):
    try:
        return [
            t for t in trade_trend
            if (current_time - parse_trade_trend_time(t['minute']).timestamp()) < 300
        ]
    except Exception as e:
        logging.warning(f"Failed to filter recent trades: {e}")
        return trade_trend

def fetch_1hr_candles(ticker, limit=10):
    try:
        conn = get_db_connection()
        if not conn:
            logging.error("🚨 No database connection for fetching 1hr candles")
            return []
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT open, high, low, close, ma_10, ma_50, doji_type
                FROM candles
                WHERE token_pair = %s
                AND timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (f"{ticker}/USD_1h", (datetime.now(timezone.utc) - timedelta(hours=limit)).strftime("%Y-%m-%d %H:%M:00"), limit))
            candles = cur.fetchall()
            if len(candles) >= limit:
                logging.debug(f"Fetched {len(candles)} 1-hour candles for {ticker}")
                return candles
            
            # Fallback to 1-minute candles
            cur.execute("""
                SELECT open, high, low, close, ma_10, ma_50, doji_type
                FROM candles
                WHERE token_pair = %s
                AND timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (f"{ticker}/USD", (datetime.now(timezone.utc) - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:00"), 60))
            minute_candles = cur.fetchall()
            if len(minute_candles) >= 1:
                prices = [float(c['close']) for c in minute_candles]
                candles = [{
                    'open': prices[0],
                    'high': max(prices),
                    'low': min(prices),
                    'close': prices[-1],
                    'ma_10': np.mean(prices[-min(10, len(prices)):]) if len(prices) >= 1 else None,
                    'ma_50': np.mean(prices[-min(50, len(prices)):]) if len(prices) >= 1 else None,
                    'doji_type': 'None'
                }]
                logging.debug(f"Aggregated {len(minute_candles)} 1-min candles into 1-hour candle for {ticker}")
            else:
                logging.warning(f"Insufficient 1-min candle data ({len(minute_candles)} candles) for {ticker}")
                return []
        return candles
    except Exception as e:
        logging.error(f"Failed to fetch 1hr candles: {e}")
        return []
    finally:
        if conn:
            conn.close()

def detect_15min_trend(candles, current_price, avg_buy_price):
    if not candles or not isinstance(candles, list) or not all(isinstance(c, dict) for c in candles):
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT open, high, low, close, ma_10, ma_50, doji_type
                        FROM candles
                        WHERE token_pair = %s
                        AND timestamp >= %s
                        ORDER BY timestamp DESC
                        LIMIT %s
                    """, (f"JELLY/USD", (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:00"), 15))
                    minute_candles = cur.fetchall()
                    if len(minute_candles) >= 1:
                        prices = [float(c['close']) for c in minute_candles]
                        candles = [{
                            'open': prices[0],
                            'high': max(prices),
                            'low': min(prices),
                            'close': prices[-1],
                            'ma_10': np.mean(prices[-min(10, len(prices)):]) if len(prices) >= 1 else None,
                            'ma_50': np.mean(prices[-min(50, len(prices)):]) if len(prices) >= 1 else None,
                            'doji_type': 'None'
                        }]
                        logging.debug(f"Aggregated {len(minute_candles)} 1-min candles into 15-min trend")
                    else:
                        logging.warning(f"Insufficient 1-min candle data ({len(minute_candles)} candles)")
            except Exception as e:
                logging.error(f"Failed to fetch 1-min candles: {e}")
            finally:
                conn.close()
        if not candles or not isinstance(candles, list) or not all(isinstance(c, dict) for c in candles):
            logging.warning("Insufficient or invalid candle data for trend analysis")
            return "sideways", avg_buy_price * 1.01 if avg_buy_price > 0 else current_price * 1.01

    closes = [float(candle['close']) for candle in candles]
    ma_10 = np.mean([float(candle['ma_10']) for candle in candles if candle['ma_10'] is not None]) if any(candle['ma_10'] is not None for candle in candles) else closes[-1]
    ma_50 = np.mean([float(candle['ma_50']) for candle in candles if candle['ma_50'] is not None]) if any(candle['ma_50'] is not None for candle in candles) else closes[-1]

    bullish_count = sum(1 for candle in candles if float(candle['close']) > float(candle['open']) and candle['doji_type'] == 'None')
    bearish_count = sum(1 for candle in candles if float(candle['close']) < float(candle['open']) and candle['doji_type'] == 'None')
    doji_count = sum(1 for candle in candles if candle['doji_type'] != 'None')

    if bullish_count > bearish_count and current_price > ma_10 * 1.005 and current_price > ma_50:
        trend = "uptrend"
    elif bearish_count > bullish_count and current_price < ma_10 * 0.995 and current_price < ma_50:
        trend = "downtrend"
    else:
        trend = "sideways"

    exit_target = avg_buy_price * (1 + PROFIT_THRESHOLD) if avg_buy_price > 0 else current_price * (1 + PROFIT_THRESHOLD)

    logging.debug(f"15min Trend: {trend}, Bullish={bullish_count}, Bearish={bearish_count}, Doji={doji_count}, Price=${current_price:.8f}, MA_10=${ma_10:.8f}, MA_50=${ma_50:.8f}, Exit Target=${exit_target:.8f}")
    return trend, exit_target

def trade_logic(tracker: TradeTracker, ticker: str, token_mint: Pubkey, wallet: Keypair, state: dict):
    current_time = time.time()
    latency = random.uniform(LATENCY_MIN, LATENCY_MAX)
    time.sleep(latency)

    # Fetch API data
    data = fetch_data()
    api_data = {
        "price": float(data.get("price", 0.0)),
        "sea_life_score": float(data.get("sea_life_score", calculate_moving_averages(data.get("classifications", {})))),
        "buys": int(data.get("buys", 0)),
        "sells": int(data.get("sells", 0)),
        "doji_signal": data.get("doji_signal", None),
        "trend_stats": data.get("trend_stats", {})
    }

    # Validate price
    if api_data["price"] <= 0:
        logging.error("🚨 Invalid price from API: $0.0, skipping trade")
        return {
            "initial_snipe_done": state.get("initial_snipe_done", False),
            "api_data": api_data,
            "trend": "sideways",
            "exit_target": 0.0,
            "action": color("HOLD", "yellow", bold=True),
            "reason": "Invalid price from API"
        }

    # Fetch SOL price from sol_price.json
    sol_price = 180.0  # Fallback value
    SOL_PRICE_JSON_PATH = "/home/safe-pump/archon/raydium/sol_price.json"
    try:
        if os.path.exists(SOL_PRICE_JSON_PATH):
            with open(SOL_PRICE_JSON_PATH, 'r') as f:
                sol_price_data = json.load(f)
                sol_price = float(sol_price_data.get("sol_usd", 180.0))
                sol_price_timestamp = sol_price_data.get("timestamp", "")
                if sol_price <= 0:
                    logging.warning("⚠️ Invalid SOL price in sol_price.json, using fallback: $180")
                    sol_price = 180.0
                elif sol_price_timestamp:
                    timestamp_dt = datetime.datetime.strptime(sol_price_timestamp, "%Y-%m-%d %H:%M:%S")
                    if (datetime.datetime.utcnow() - timestamp_dt).total_seconds() > 600:
                        logging.warning("⚠️ SOL price is stale (>10min), using fallback: $180")
                        sol_price = 180.0
        else:
            logging.warning(f"⚠️ {SOL_PRICE_JSON_PATH} not found, using fallback SOL price: $180")
    except Exception as e:
        logging.warning(f"⚠️ Failed to load SOL price from {SOL_PRICE_JSON_PATH}: {e}, using fallback: $180")
    state["sol_price"] = sol_price
    logging.debug(f"💰 SOL Price: ${sol_price:.2f}")

    # Fetch wallet balances
    try:
        wallet_balance = get_sol_balance(wallet)
        token_balance = get_token_balance(wallet, token_mint)
        state["cached_sol_balance"] = wallet_balance
        state["cached_token_balance"] = token_balance
        tracker.sync_with_wallet(wallet_balance, token_balance, force_sync=True)
        logging.debug(f"💰 Wallet: SOL={wallet_balance:.6f}, Tokens={token_balance:.2f}")
    except Exception as e:
        logging.warning(f"⚠️ Failed to fetch balances: {e}")
        wallet_balance = state.get("cached_sol_balance", 0.0)
        token_balance = state.get("cached_token_balance", 0.0)
        tracker.sync_with_wallet(wallet_balance, token_balance, force_sync=True)

    sol_liquid = tracker.sol_liquid_available
    token_amount = tracker.token_amount
    avg_buy_price = tracker.avg_buy_price
    time_since_last_trade = current_time - tracker.last_trade_time
    min_hold_time = 300  # 5 minutes before stop-loss

    # Validate avg_buy_price
    if token_amount > 0 and (avg_buy_price <= 0 or avg_buy_price > api_data["price"] * 1000 or avg_buy_price < api_data["price"] / 1000):
        logging.warning(f"⚠️ Invalid avg_buy_price: ${avg_buy_price:.8f}, resetting to current price")
        avg_buy_price = api_data["price"]
        tracker.avg_buy_price = avg_buy_price
        tracker.save_to_state(state)

    # Load candles
    candles = data.get("candle_trend", [])
    if not candles or not isinstance(candles, list) or not all(isinstance(c, dict) for c in candles):
        logging.warning("⚠️ No valid candles from API, fetching from database")
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT open, high, low, close, ma_10, ma_50, doji_type
                        FROM candles
                        WHERE token_pair = %s
                        AND timestamp >= %s
                        ORDER BY timestamp DESC
                        LIMIT 15
                    """, (f"{ticker}/USD", (datetime.datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:00")))
                    candles = cur.fetchall()
                    candles = [
                        {
                            "open": float(c['open']),
                            "high": float(c['high']),
                            "low": float(c['low']),
                            "close": float(c['close']),
                            "ma_10": float(c['ma_10']) if c['ma_10'] is not None else None,
                            "ma_50": float(c['ma_50']) if c['ma_50'] is not None else None,
                            "doji_type": c['doji_type']
                        } for c in candles
                    ]
                    logging.debug(f"Fetched {len(candles)} candles directly from database")
            except Exception as e:
                logging.error(f"🚨 Failed to fetch candles from database: {e}")
                candles = []
            finally:
                conn.close()
        if not candles:
            logging.warning("⚠️ No candles available, using fallback")
            candles = [{"open": api_data["price"], "high": api_data["price"], "low": api_data["price"], "close": api_data["price"], "ma_10": None, "ma_50": None, "doji_type": "None"}]

    # Detect trend
    try:
        trend, exit_target = detect_15min_trend(candles, api_data["price"], avg_buy_price)
        if exit_target > api_data["price"] * 100 or exit_target < api_data["price"]:
            logging.warning(f"⚠️ Invalid exit_target: ${exit_target:.8f}, setting to price * (1 + PROFIT_THRESHOLD)")
            exit_target = api_data["price"] * (1 + PROFIT_THRESHOLD)
    except Exception as e:
        logging.error(f"🚨 Error in detect_15min_trend: {e}")
        trend = "sideways"
        exit_target = avg_buy_price * (1 + PROFIT_THRESHOLD) if avg_buy_price > 0 else api_data["price"] * (1 + PROFIT_THRESHOLD)
    state["trend_15min"] = trend
    state["exit_target"] = exit_target
    logging.debug(f"📈 Trend={trend}, Exit Target=${exit_target:.8f}")

    # Calculate profit potential
    profit_potential = (api_data["price"] - avg_buy_price) / avg_buy_price if avg_buy_price > 0 else 0
    logging.debug(f"📊 Profit Potential={profit_potential:.2%}, Avg Buy Price=${avg_buy_price:.8f}")

    # Market signals
    recent_prices = [p["price"] for p in tracker.price_history if p["timestamp"] > current_time - 60][-5:]
    price_stagnant = len(recent_prices) >= 2 and max(recent_prices) - min(recent_prices) < api_data["price"] * 0.005
    market_signal = api_data["sea_life_score"] > state["market_trends"].get("avg_sea_life_score", 0.0) * 1.15 and float(api_data["buys"]) >= float(api_data["sells"]) * 1.2
    logging.debug(f"📊 Market: Score={api_data['sea_life_score']:.2f}, Avg={state['market_trends'].get('avg_sea_life_score', 0.0):.2f}, Buys={api_data['buys']}, Sells={api_data['sells']}, Signal={market_signal}")

    # Initialize state
    if "initial_sol" not in state:
        state["initial_sol"] = wallet_balance
    total_sol = sol_liquid
    # Calculate unrealized profit
    token_value_usd = token_amount * api_data["price"]
    token_value_sol = token_value_usd / sol_price if sol_price > 0 else 0
    unrealized_profit = token_value_sol - tracker.current_roll if token_amount > 0 else 0.0
    # Validate unrealized profit
    if abs(unrealized_profit) > wallet_balance + token_value_sol:
        logging.warning(f"⚠️ Unrealized profit {unrealized_profit:.6f} SOL implausible, resetting to 0")
        unrealized_profit = 0.0
    logging.debug(f"💰 Unrealized Profit: {unrealized_profit:.6f} SOL (Token Value={token_value_sol:.6f} SOL, Current Roll={tracker.current_roll:.6f} SOL)")

    # Calculate progress
    progress = 0.0
    if avg_buy_price > 0 and exit_target > avg_buy_price:
        progress = max(0.0, min(((api_data["price"] - avg_buy_price) / (exit_target - avg_buy_price)) * 100, 100.0))
    logging.debug(f"📊 Progress: {progress:.1f}% to Exit Target")

    # Update price history
    if not tracker.price_history or api_data["price"] != tracker.price_history[-1]["price"]:
        state["last_price_update"] = current_time
        tracker.price_history.append({"price": api_data["price"], "timestamp": current_time})
        tracker.price_history = [p for p in tracker.price_history if current_time - p["timestamp"] < TREND_DURATION]

    txid = ""
    amount_out = 0.0
    action = ""
    reason = ""

    min_sol_required = MINIMUM_SOL_REQUIRED + MIN_LIQUID_RESERVE + NETWORK_FEE
    if sol_liquid < min_sol_required:
        action = color("HOLD", "yellow", bold=True)
        reason = f"Insufficient SOL: need {min_sol_required:.6f}, have {sol_liquid:.6f}"
        logging.warning(reason)
    elif token_amount == 0:
        # Buy logic: allow buys in uptrend or sideways with strong market signal
        if (trend in ["uptrend", "sideways"] and market_signal and current_time - tracker.last_buy_attempt >= BUY_COOLDOWN):
            buy_amount = min(sol_liquid * 0.15, sol_liquid - MIN_LIQUID_RESERVE)
            if buy_amount < MIN_SWAP_SOL:
                action = color("HOLD", "yellow", bold=True)
                reason = f"Buy amount too low: {buy_amount:.6f} SOL"
            else:
                txid, amount_out = execute_buy_swap(buy_amount, True, ticker, api_data["price"], wallet, token_mint, state, tracker)
                action = color("BUY", "blue", bold=True)
                logging.debug(f"📈 Buy attempt: SOL={buy_amount:.6f}, Expected Tokens={amount_out:.2f}, TXID={txid}")
                if amount_out > 0:
                    new_token_balance = get_token_balance(wallet, token_mint)
                    new_sol_balance = get_sol_balance(wallet)
                    actual_buy_price = buy_amount / amount_out if amount_out > 0 else api_data["price"]
                    tracker.sync_with_wallet(new_sol_balance, new_token_balance, force_sync=True)
                    tracker.avg_buy_price = actual_buy_price
                    state["cached_sol_balance"] = new_sol_balance
                    state["cached_token_balance"] = new_token_balance
                    new_exit_target = actual_buy_price * (1 + PROFIT_THRESHOLD)
                    state["exit_target"] = new_exit_target
                    update_state_after_trade(
                        state, "BUY", amount_out, buy_amount, actual_buy_price, txid,
                        api_data["sea_life_score"], 0.0, actual_buy_price, new_exit_target
                    )
                    reason = f"Bought {amount_out:.2f} {ticker} for {buy_amount:.6f} SOL @ ${actual_buy_price:.8f}, TX={txid}"
                    logging.info(f"🖋️ {reason}")
                else:
                    reason = f"❌ Buy failed: TXID={txid}, Out={amount_out}"
                    update_state_after_trade(
                        state, "BUY_FAILED", 0.0, buy_amount, api_data["price"], txid,
                        api_data["sea_life_score"], 0.0, tracker.avg_buy_price, state["exit_target"]
                    )
                    logging.warning(reason)
        else:
            action = color("HOLD", "yellow", bold=True)
            reason = f"Waiting for buy: Trend={trend}, Signal={market_signal}, Cooldown={max(0, BUY_COOLDOWN - (current_time - tracker.last_buy_attempt)):.1f}s"
            logging.debug(f"Holding: {reason}")
    else:
        # Buy logic: allow averaging down in sideways or downtrend
        if (trend in ["sideways", "downtrend"] and market_signal and api_data["price"] < avg_buy_price * 0.99 and current_time - tracker.last_buy_attempt >= BUY_COOLDOWN):
            buy_amount = min(sol_liquid * 0.1, sol_liquid - MIN_LIQUID_RESERVE)
            if buy_amount < MIN_SWAP_SOL:
                action = color("HOLD", "yellow", bold=True)
                reason = f"Buy amount too low: {buy_amount:.6f} SOL"
            else:
                txid, amount_out = execute_buy_swap(buy_amount, True, ticker, api_data["price"], wallet, token_mint, state, tracker)
                action = color("BUY", "blue", bold=True)
                logging.debug(f"📈 Buy attempt: SOL={buy_amount:.6f}, Expected Tokens={amount_out:.2f}, TXID={txid}")
                if amount_out > 0:
                    new_token_balance = get_token_balance(wallet, token_mint)
                    new_sol_balance = get_sol_balance(wallet)
                    actual_buy_price = buy_amount / amount_out if amount_out > 0 else api_data["price"]
                    tracker.sync_with_wallet(new_sol_balance, new_token_balance, force_sync=True)
                    total_cost = (tracker.token_amount * tracker.avg_buy_price) + (amount_out * actual_buy_price)
                    total_tokens = tracker.token_amount + amount_out
                    tracker.avg_buy_price = total_cost / total_tokens if total_tokens > 0 else actual_buy_price
                    state["cached_sol_balance"] = new_sol_balance
                    state["cached_token_balance"] = new_token_balance
                    new_exit_target = tracker.avg_buy_price * (1 + PROFIT_THRESHOLD)
                    state["exit_target"] = new_exit_target
                    update_state_after_trade(
                        state, "BUY", amount_out, buy_amount, actual_buy_price, txid,
                        api_data["sea_life_score"], 0.0, tracker.avg_buy_price, new_exit_target
                    )
                    reason = f"Bought {amount_out:.2f} {ticker} for {buy_amount:.6f} SOL @ ${actual_buy_price:.8f} to average down, TX={txid}"
                    logging.info(f"🖋️ {reason}")
                else:
                    reason = f"❌ Buy failed: TXID={txid}, Out={amount_out}"
                    update_state_after_trade(
                        state, "BUY_FAILED", 0.0, buy_amount, api_data["price"], txid,
                        api_data["sea_life_score"], 0.0, tracker.avg_buy_price, state["exit_target"]
                    )
                    logging.warning(reason)
        # Sell logic: only sell near exit target or at stop-loss after min hold time
        elif (trend == "uptrend" and api_data["price"] >= exit_target * 0.995 and time_since_last_trade >= min_hold_time and current_time - tracker.last_sell_attempt >= SELL_COOLDOWN) or \
             (avg_buy_price > 0 and profit_potential <= STOP_LOSS_THRESHOLD and trend == "downtrend" and time_since_last_trade >= min_hold_time):
            sell_amount = token_amount
            expected_sol = sell_amount * api_data["price"] / sol_price * (1 - FEE_PER_TRADE) - NETWORK_FEE
            if expected_sol <= 0:
                action = color("HOLD", "yellow", bold=True)
                reason = f"Expected sell amount too low: {expected_sol:.6f} SOL"
                logging.debug(reason)
            else:
                txid, amount_out = execute_sell_swap(sell_amount, False, ticker, api_data["price"], wallet, token_mint, state, tracker)
                action = color("SELL", "red", bold=True)
                logging.debug(f"📈 Sell attempt: Amount={sell_amount:.2f}, Expected={expected_sol:.6f}, TXID={txid}, Out={amount_out:.6f}")
                if amount_out > 0 or (txid and len(txid) > 0):
                    new_token_balance = get_token_balance(wallet, token_mint)
                    new_sol_balance = get_sol_balance(wallet)
                    tracker.sync_with_wallet(new_sol_balance, new_token_balance, force_sync=True)
                    state["cached_sol_balance"] = new_sol_balance
                    state["cached_token_balance"] = new_token_balance
                    state["last_pl"] = amount_out - tracker.current_roll if amount_out > 0 else (new_sol_balance - sol_liquid) - tracker.current_roll
                    state["last_sell_price"] = api_data["price"]
                    total_sol = tracker.sol_liquid_available
                    state["flip_count"] += 1
                    state["cycle_start_time"] = current_time
                    update_state_after_trade(
                        state, "SELL", sell_amount, amount_out if amount_out > 0 else new_sol_balance - sol_liquid, api_data["price"], txid,
                        api_data["sea_life_score"], state["last_pl"], avg_buy_price, api_data["price"] * (1 + PROFIT_THRESHOLD)
                    )
                    reason = f"Sold {sell_amount:.2f} {ticker} for {(amount_out if amount_out > 0 else new_sol_balance - sol_liquid):.6f} SOL due to {'exit target' if api_data['price'] >= exit_target * 0.995 else 'stop loss'}, TX={txid}"
                    logging.info(f"🖌️ {reason}")
                    if new_token_balance == 0:
                        tracker.reset_buy_history()
                        state["exit_target"] = api_data["price"] * (1 + PROFIT_THRESHOLD)
                else:
                    reason = f"❌ Sell failed: TXID={txid}, Out={amount_out}"
                    update_state_after_trade(
                        state, "SELL_FAILED", sell_amount, 0.0, api_data["price"], txid,
                        api_data["sea_life_score"], 0.0, avg_buy_price, state["exit_target"]
                    )
                    logging.warning(reason)
        else:
            action = color("HOLD", "yellow", bold=True)
            reason = f"Holding: Trend={trend}, Price=${api_data['price']:.6f}, Target=${exit_target:.6f}, Profit={profit_potential:.2%}"
            logging.debug(f"Holding: {reason}")

    logging.info(f"🎮 Progress: {progress:.1f}% to target (Unrealized Profit={unrealized_profit:.6f} SOL, Price=${api_data['price']:.6f}, Target=${exit_target:.6f})")
    tracker.save_to_state(state)
    save_state(state)

    return {
        "initial_snipe_done": state.get("initial_snipe_done", False),
        "api_data": api_data,
        "trend": trend,
        "exit_target": exit_target,
        "action": action,
        "reason": reason,
        "progress": progress  # Added for trade summary
    }

def dump_on_boot(tracker, ticker, token_mint, wallet, state):
    sol_balance = state["cached_sol_balance"]
    token_balance = state["cached_token_balance"]
    try:
        sol_balance = get_sol_balance(wallet) or sol_balance
        token_balance = get_token_balance(wallet, token_mint) or token_balance
        state["cached_sol_balance"] = sol_balance
        state["cached_token_balance"] = token_balance
        logging.info(f"🛑 Dump on boot: Fetched balances - SOL={sol_balance:.6f}, Tokens={token_balance:.2f}")
    except Exception as e:
        logging.warning(f"⚠️ Failed to fetch wallet balances for dump, using cached: {e}")

    tracker.sync_with_wallet(sol_balance, token_balance, force_sync=True)
    
    if tracker.token_amount > 0:
        data = fetch_data()
        price = data.get("price", 0.03066045)
        trend, exit_target = detect_15min_trend([], price, tracker.avg_buy_price)
        logging.info(f"🛑 Dump on boot: Attempting to sell {tracker.token_amount:.2f} {ticker} @ ${price:.8f}")
        txid, sol_received = execute_sell_swap(tracker.token_amount, False, ticker, price, wallet, token_mint, state, tracker)
        if sol_received > 0:
            profit = sol_received - tracker.current_roll
            state["last_cycle_pl"] = profit
            state["cached_sol_balance"] = tracker.sol_liquid_available + tracker.sol_trimmed
            update_state_after_trade(state, "SELL", tracker.token_amount, sol_received, price, txid, 0.0, profit, tracker.avg_buy_price, exit_target)
            logging.info(f"🛑 Dump on boot: Sold {tracker.token_amount:.2f} {ticker} for {sol_received:.6f} SOL @ ${price:.8f}, Profit={profit:.6f}, TXID={txid}")
            print(color("DUMP", 'red', bold=True) + " - Sold all tokens on startup")
        else:
            logging.error(f"🚨 Dump on boot failed: No tokens sold")
            print(color("DUMP", 'red', bold=True) + " - Failed to sell tokens on startup")
    else:
        logging.info(f"ℹ️ Dump on boot: No tokens to sell")
        print(color("DUMP", 'red', bold=True) + " - No tokens to sell on startup")
    
    print_balances(tracker, ticker, price if ticker else 0.0, state)
    tracker.save_to_state(state)
    save_state(state)


def execute_snipe(tracker, ticker, token_mint, wallet, state):
    if SKIP_SNIPE or state["initial_snipe_done"]:
        logging.info(f"ℹ️ Skipping initial snipe: SKIP_SNIPE={SKIP_SNIPE}, initial_snipe_done={state['initial_snipe_done']}")
        return {
            "initial_snipe_done": True,
            "api_data": {"price": 0.0, "sea_life_score": 0.0, "buys": 0, "sells": 0, "doji_signal": None},
            "trend": "none",
            "exit_target": 0.0,
            "action": color("SKIP SNIPE", "yellow", bold=True),
            "reason": "Snipe skipped due to configuration or prior completion"
        }

    if tracker.sol_liquid_available < MIN_LIQUID_RESERVE + MIN_SOL_FOR_TRADE:
        logging.warning(f"⚠️ Insufficient SOL for snipe: {tracker.sol_liquid_available:.6f} SOL available")
        state["initial_snipe_done"] = True
        save_state(state)
        return {
            "initial_snipe_done": True,
            "api_data": {"price": 0.0, "sea_life_score": 0.0, "buys": 0, "sells": 0, "doji_signal": None},
            "trend": "none",
            "exit_target": 0.0,
            "action": color("HOLD", "yellow", bold=True),
            "reason": f"Insufficient SOL for snipe: {tracker.sol_liquid_available:.6f} available"
        }

    data = fetch_data()
    api_data = {
        "price": data.get("price", 0.03066045),
        "sea_life_score": float(data.get("sea_life_score", calculate_moving_averages(data.get("classifications", {})))),
        "buys": data.get("buys", 0),
        "sells": data.get("sells", 0),
        "doji_signal": data.get("doji_signal", None)
    }
    snipe_amount = min(state["initial_sol_balance"] * SNIPER_PERCENTAGE, tracker.sol_liquid_available - MIN_LIQUID_RESERVE)
    logging.info(f"🔫 Executing initial snipe: {snipe_amount:.6f} SOL for {ticker} @ ${api_data['price']:.8f}")

    try:
        txid, amount_out = execute_buy_swap(snipe_amount, True, ticker, api_data["price"], wallet, token_mint, state, tracker)
        if amount_out > 0:
            state["cached_sol_balance"] = tracker.sol_liquid_available + tracker.sol_trimmed
            state["cached_token_balance"] = tracker.token_amount
            update_state_after_trade(state, "BUY", amount_out, snipe_amount, api_data["price"], txid, api_data["sea_life_score"], avg_buy_price=tracker.avg_buy_price, exit_target=tracker.avg_buy_price * (1 + PROFIT_THRESHOLD))
            logging.info(f"🔫 Snipe successful: {amount_out:.2f} {ticker} for {snipe_amount:.6f} SOL @ ${api_data['price']:.8f}, TXID={txid}, New Avg Buy Price=${tracker.avg_buy_price:.8f}")
            action = color("SNIPE", "cyan", bold=True)
            reason = f"Bought {amount_out:.2f} {ticker} for {snipe_amount:.6f} SOL"
        else:
            logging.warning("⚠️ Snipe failed: No tokens received")
            action = color("SNIPE FAILED", "red", bold=True)
            reason = "Failed (no tokens)"
    except Exception as e:
        logging.error(f"🚨 Snipe failed: {e}")
        action = color("SNIPE FAILED", "red", bold=True)
        reason = f"Failed: {str(e)}"

    state["initial_snipe_done"] = True
    tracker.save_to_state(state)
    save_state(state)

    return {
        "initial_snipe_done": True,
        "api_data": api_data,
        "trend": "none",  # Snipe doesn't use trend
        "exit_target": tracker.avg_buy_price * (1 + PROFIT_THRESHOLD) if amount_out > 0 else 0.0,
        "action": action,
        "reason": reason
    }

def print_trade_summary(ticker, tracker, state, api_data, trend, exit_target, action, reason):
    terminal_width = shutil.get_terminal_size().columns
    print("\n" + "=" * terminal_width)
    print(color(f"Trade Summary - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "cyan", bold=True).center(terminal_width))
    print("=" * terminal_width)
    
    # API Data
    print(color(f"Price: ${api_data['price']:.6f}", "yellow"))
    print(color(f"Sea Life Score: {api_data['sea_life_score']:.2f}", "yellow"))
    print(color(f"Buys: {api_data['buys']} | Sells: {api_data['sells']}", "yellow"))
    print(color(f"Doji Signal: {api_data['doji_signal'] or 'None'}", "yellow"))
    
    # Balances
    print(color(f"SOL Liquid Available: {tracker.sol_liquid_available:.6f}", "green"))
    print(color(f"SOL Trimmed: {tracker.sol_trimmed:.6f}", "green"))
    print(color(f"Total {ticker} Accumulated: {tracker.token_amount:.2f}", "yellow"))
    
    # Trade Info
    print(color(f"Current Roll: {tracker.current_roll:.6f} SOL", "green"))
    print(color(f"Last Cycle P/L: {state['last_cycle_pl']:.6f} SOL", "green" if state["last_cycle_pl"] >= 0 else "red"))
    print(color(f"Avg Buy Price: ${tracker.avg_buy_price:.6f} | Exit Target: ${exit_target:.6f} | Trend: {trend}", "yellow"))
    print(color(f"Flips: {state['flip_count']} | Progress to Exit: {max(0.0, min(((api_data['price'] - tracker.avg_buy_price) / (exit_target - tracker.avg_buy_price)) * 100, 100.0)) if tracker.avg_buy_price > 0 and exit_target > tracker.avg_buy_price else 0.0:.1f}%", "green"))
    
    # Action
    print(color(f"{action} - {reason}", "white", bold=True))
    print("=" * terminal_width + "\n")

def main():
    global wallet
    try:
        logging.info("📝 Starting main function")
        wallet = load_wallet()
        logging.info(f"🔑 Wallet loaded: {wallet.pubkey()}")
    except Exception as e:
        logging.error(f"🚨 Failed to load wallet: {e}")
        sys.exit(1)

    try:
        state = load_state()
        if not isinstance(state, dict):
            logging.error(f"🚨 Loaded state is not a dictionary: {state}")
            sys.exit(1)
        logging.info("📝 State loaded successfully")
    except Exception as e:
        logging.error(f"🚨 Failed to load state: {e}")
        sys.exit(1)

    if "initial_sol_balance" not in state:
        initial_sol = state.get("cached_sol_balance", 0.0)
        try:
            initial_sol = get_sol_balance(wallet) or initial_sol
            state["cached_sol_balance"] = initial_sol
            logging.info(f"💰 Initial SOL balance: {initial_sol}")
        except Exception as e:
            logging.warning(f"⚠️ Failed to fetch initial SOL balance, using cached value {initial_sol}: {e}")
        state["initial_sol_balance"] = initial_sol
        save_state(state)
    else:
        initial_sol = state["initial_sol_balance"]
        logging.info(f"💰 Loaded initial SOL balance from state: {initial_sol}")

    try:
        constants = load_constants()
        ticker = constants["ticker"]
        token_mint = constants["mint"]
        logging.info(f"🎯 Loaded constants: Ticker={ticker}, Mint={token_mint}")
    except Exception as e:
        logging.error(f"🚨 Failed to load constants: {e}")
        sys.exit(1)

    try:
        tracker = TradeTracker(initial_sol, state)
        logging.info("📈 TradeTracker initialized")
    except Exception as e:
        logging.error(f"🚨 Failed to initialize TradeTracker: {e}")
        sys.exit(1)

    try:
        initial_token_balance = get_token_balance(wallet, token_mint) or state["cached_token_balance"]
        state["cached_token_balance"] = initial_token_balance
        logging.info(f"💰 Initial token balance: {initial_token_balance} 🐱")
    except Exception as e:
        logging.warning(f"⚠️ Failed to fetch initial token balance, using cached value {state['cached_token_balance']}: {e}")

    try:
        tracker.token_amount = state["cached_token_balance"]
        tracker.sync_with_wallet(initial_sol, initial_token_balance, force_sync=True)
        logging.info("🎯 Tracker synced with wallet")
    except Exception as e:
        logging.error(f"🚨 Failed to sync tracker with wallet: {e}")
        sys.exit(1)

    try:
        welcome_screen(ticker, initial_sol)
        logging.info("🖥️ Welcome screen displayed")
    except Exception as e:
        logging.error(f"🚨 Failed to display welcome screen: {e}")
        sys.exit(1)

    # Execute initial snipe
    try:
        snipe_result = execute_snipe(tracker, ticker, token_mint, wallet, state)
        state["initial_snipe_done"] = snipe_result["initial_snipe_done"]
        print_trade_summary(
            ticker,
            tracker,
            state,
            snipe_result["api_data"],
            snipe_result["trend"],
            snipe_result["exit_target"],
            snipe_result["action"],
            snipe_result["reason"]
        )
    except Exception as e:
        logging.error(f"🚨 Snipe execution failed: {e}")
        print_trade_summary(
            ticker,
            tracker,
            state,
            {"price": 0.0, "sea_life_score": 0.0, "buys": 0, "sells": 0, "doji_signal": None},
            "none",
            0.0,
            color("SNIPE FAILED", "red", bold=True),
            f"Snipe failed: {str(e)}"
        )

    if DUMP_ON_BOOT and (SKIP_SNIPE or state["initial_snipe_done"]):
        try:
            dump_on_boot(tracker, ticker, token_mint, wallet, state)
            logging.info("🛑 DUMP_ON_BOOT executed")
            # Print summary after dump
            data = fetch_data()
            api_data = {
                "price": data.get("price", 0.03066045),
                "sea_life_score": float(data.get("sea_life_score", calculate_moving_averages(data.get("classifications", {})))),
                "buys": data.get("buys", 0),
                "sells": data.get("sells", 0),
                "doji_signal": data.get("doji_signal", None)
            }
            print_trade_summary(
                ticker,
                tracker,
                state,
                api_data,
                state.get("trend_15min", "none"),
                state.get("exit_target", 0.0),
                color("DUMP", "red", bold=True),
                "Dump on boot executed"
            )
        except Exception as e:
            logging.error(f"🚨 DUMP_ON_BOOT failed: {e}")
            print_trade_summary(
                ticker,
                tracker,
                state,
                {"price": 0.0, "sea_life_score": 0.0, "buys": 0, "sells": 0, "doji_signal": None},
                "none",
                0.0,
                color("DUMP FAILED", "red", bold=True),
                f"Dump on boot failed: {str(e)}"
            )

    while True:
        try:
            # Execute trade logic and get summary data
            trade_result = trade_logic(tracker, ticker, token_mint, wallet, state)
            state["initial_snipe_done"] = trade_result["initial_snipe_done"]
            
            # Print formatted trade summary
            print_trade_summary(
                ticker,
                tracker,
                state,
                trade_result["api_data"],
                trade_result["trend"],
                trade_result["exit_target"],
                trade_result["action"],
                trade_result["reason"]
            )
        except Exception as e:
            logging.error(f"🚨 Error in trade loop: {e}")
            print_trade_summary(
                ticker,
                tracker,
                state,
                {"price": 0.0, "sea_life_score": 0.0, "buys": 0, "sells": 0, "doji_signal": None},
                "none",
                0.0,
                color("ERROR", "red", bold=True),
                f"Trade loop error: {str(e)}"
            )
        time.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    main()
