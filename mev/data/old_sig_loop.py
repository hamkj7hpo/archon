import os
import json
import time
import sys
import logging
import subprocess
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, Column, Integer, Float, Boolean, String, Numeric, update, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import schedule
import signal
import db
from db import Base
from db import PROCESSED_WHALES_FILE, VOLUME_MONITOR_FILE, DATABASE_URL, DOJI_DATA, engine
from classes import CandlestickData, WhaleDetector
from db import load_processed_whale_trades, save_processed_whale_trades, load_volume_monitor, save_volume_monitor, connect_to_db
from candles import detect_doji_candles, detect_and_save_engulfing_candles




def signal_handler(sig, frame):
    logging.info("Gracefully shutting down...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


# Data loading function
def load_data(engine):
    try:
        # Fetch data from the candlestick_data table
        candlestick_data = pd.read_sql("SELECT * FROM candlestick_data;", engine)
        
        # Fetch data from the whale_detector table
        whale_detector_data = pd.read_sql("SELECT * FROM whale_detector;", engine)
        
        # Return both datasets
        return candlestick_data, whale_detector_data
    except Exception as e:
        # Log any errors encountered
        logging.error(f"Error loading data: {e}")
        
        # Return None for both datasets in case of an error
        return None, None

def detect_whale_trade(whale_detector_data):
    # Check for whale trades
    whale_trades = whale_detector_data[whale_detector_data['classification'] == "🐋"]
    new_whale_trades = []

    for _, trade in whale_trades.iterrows():
        trade_id = trade['id']
        if trade_id not in processed_whales:  # Only add new trades
            new_whale_trades.append(trade)  # Append the whole trade, not just the ID
            processed_whales.add(trade_id)  # Mark as processed

    if new_whale_trades:
        save_processed_whale_trades(processed_whales)  # Save updated processed trades
        logging.info(f"Detected new whale trades: {len(new_whale_trades)} 🐋")
        for trade in new_whale_trades:
            logging.debug(f"New whale trade details: {trade}")  # Log trade details
        return new_whale_trades  # Return the list of new trades

    return []  # Return empty list if no new trades are found


WHALE_THRESHOLD = 100000  # Set your whale threshold here
processed_whales = set()  # This will store the hashes of processed whale trades


def process_whales(whale_detector_data):
    new_whales = 0
    for trade in whale_detector_data:
        if isinstance(trade, dict):
            try:
                trade_value = float(trade.get('trade_value', 0))  # Default to 0 if missing
            except ValueError:
                logging.warning(f"Skipping trade with invalid 'trade_value': {trade}")
                continue
            
            # Only consider trades that exceed the whale threshold
            if trade_value >= WHALE_THRESHOLD:
                logging.info(f"Whale detected with trade value: {trade_value}")
                processed_whales.add(trade['trade_hash'])
                new_whales += 1
            else:
                logging.debug(f"Trade value {trade_value} is below threshold, skipping.")
        else:
            logging.debug(f"Skipping invalid trade entry (not a dictionary): {trade}")
    
    # Log the number of new whale trades detected
    logging.info(f"Detected {new_whales} new whale trades.")

# Initialize processed whale trades and volume monitor
processed_whales = load_processed_whale_trades()
volume_monitor = load_volume_monitor()

# Volume monitor update
def update_volume_monitor(candlestick_data, whale_detected):
    for _, row in candlestick_data.iterrows():
        if whale_detected:
            logging.info(f"Whale trade detected for token pair {row['token_pair']}.")
        else:
            volume_monitor.append(row.to_dict())
    save_volume_monitor(volume_monitor)

# Fibonacci calculation
def calculate_fibonacci_levels(candlestick_data):
    try:
        if not isinstance(candlestick_data, pd.DataFrame):
            raise ValueError("candlestick_data must be a DataFrame.")

        # Validate required columns
        required_columns = {'high', 'low'}
        if not required_columns.issubset(candlestick_data.columns):
            raise KeyError(f"candlestick_data must contain columns: {required_columns}")

        # Calculate Fibonacci levels
        recent_high = candlestick_data['high'].max()
        recent_low = candlestick_data['low'].min()
        diff = recent_high - recent_low

        FIBONACCI_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]  # Define levels if not global
        levels = {level: recent_high - (diff * level) for level in FIBONACCI_LEVELS}

        return levels
    except Exception as e:
        logging.error(f"Error in calculate_fibonacci_levels: {e}")
        return {}


def process_and_analyze_data():
    logging.info("Processing and analyzing data...")
    engine = connect_to_db()
    if engine is None:
        return

    candlestick_data, whale_detector_data = load_data(engine)
    
    if candlestick_data is None or whale_detector_data is None:
        return

    # Analyze candlestick data
    candlestick_df = pd.DataFrame(candlestick_data)
    new_dojis = detect_doji_candle(candlestick_df)
    new_bullish_engulfings = detect_bullish_engulfing(candlestick_df)
    new_bearish_engulfings = detect_bearish_engulfing(candlestick_df)

    # Analyze whale trades
    process_whales(whale_detector_data)

    logging.info("Data processing complete.")

# Initialize classification counts
creature_counts = {
    "🐋": {"total": 0, "new": 0},
    "🦈": {"total": 0, "new": 0},
    "🐟": {"total": 0, "new": 0},
    "🐙": {"total": 0, "new": 0},
    "🦀": {"total": 0, "new": 0},
    "🦐": {"total": 0, "new": 0},
    "🐚": {"total": 0, "new": 0}
}

# Calculate trading volume and classify trades


# Calculate trading volume and classify trades
def calculate_trading_volume():
    try:
        query = text("""
            SELECT 
                v.whale_wallet,
                v.detected_time,
                v.amount,
                v.token,
                v.trade_type,
                CASE
                    WHEN ABS(v.amount) > 1000000000 THEN '🐋' -- Whale
                    WHEN ABS(v.amount) > 100000000 THEN '🦈' -- Shark
                    WHEN ABS(v.amount) > 10000000 THEN '🐟' -- Fish
                    WHEN ABS(v.amount) > 1000000 THEN '🐙' -- Octopus
                    WHEN ABS(v.amount) > 500000 THEN '🦀' -- Crab
                    WHEN ABS(v.amount) > 100000 THEN '🦐' -- Shrimp
                    ELSE '🐚' -- Shell
                END AS classification
            FROM whale_detector v;
        """)

        with engine.connect() as connection:
            result = connection.execute(query)

            # Counters for each classification
            counts = {"🐋": 0, "🦈": 0, "🐟": 0, "🐙": 0, "🦀": 0, "🦐": 0, "🐚": 0}
            for row in result:
                # Accessing the row using indices
                classification = row[-1]  # Last element is 'classification'
                # Increment the corresponding classification counter
                counts[classification] += 1

            # Output the summary of detected classifications
            logging.info(
                f"Trading volume classification summary:\n"
                f"🐋 Whales: {counts['🐋']}\n"
                f"🦈 Sharks: {counts['🦈']}\n"
                f"🐟 Fish: {counts['🐟']}\n"
                f"🐙 Octopuses: {counts['🐙']}\n"
                f"🦀 Crabs: {counts['🦀']}\n"
                f"🦐 Shrimps: {counts['🦐']}\n"
                f"🐚 Shells: {counts['🐚']}"
            )

            logging.info("Volume calculation and classification completed successfully.")
    except Exception as e:
        logging.error(f"Error calculating trading volume: {e}")



def schedule_volume_calculation(candlestick_data, whale_detector_data):
    try:
        # Schedule the calculation function to run after 15 seconds
        schedule.every(45).seconds.do(calculate_trading_volume)

        logging.info("Starting the trading volume calculation scheduler...")

        # Run the scheduled task once and then exit
        schedule.run_pending()

        # Log and exit after completing the task
        logging.info("Scheduler finished, exiting...")

    except Exception as e:
        logging.error(f"An error occurred: {e}")




# Set up logging configuration for archon.py
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Create a logger for archon.py
logger = logging.getLogger()

def run_candles():
    try:
        # Running candles.py as a subprocess and redirecting its output
        logging.info("Starting candles.py subprocess... 🔄")

        process = subprocess.Popen(
            ['python3', 'candles.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Reading stdout and stderr from candles.py
        for line in process.stdout:
            # Log each line from candles.py output to the archon logger
            logger.info(line.strip())

        for line in process.stderr:
            # If there are any errors, log them as errors
            logger.error(line.strip())

        process.wait()  # Wait for the subprocess to finish

    except Exception as e:
        logger.error(f"An error occurred while running candles.py: {e}")
        raise


#Processing logic for training step
def process_and_train_step(candlestick_data, whale_detector_data, step):
    logging.info(f"Processing step {step}...")
    
    # Check for required columns in the dataset
    required_columns = ['open', 'high', 'low', 'close', 'ma_10', 'ma_50']
    if not all(col in candlestick_data.columns for col in required_columns):
        logging.warning("Missing required columns. Skipping step.")
        return

    # Calculate the target value as the average of moving averages
    candlestick_data['target'] = (candlestick_data['ma_10'] + candlestick_data['ma_50']) / 2
    logging.info(f"Target statistics: {candlestick_data['target'].describe()}")

    # Ensure sufficient data is available for the target
    if candlestick_data['target'].dropna().shape[0] < 2:
        logging.warning("Insufficient data for target. Skipping step.")
        return

    # Calculate Fibonacci levels and detect candlestick patterns
    fibonacci_levels = calculate_fibonacci_levels(candlestick_data)
    candlestick_data = detect_doji_candles(candlestick_data)
    candlestick_data = detect_and_save_engulfing_candles(candlestick_data)

    # Detect whale trades and place a trade if detected
    whale_detected = detect_whale_trade(whale_detector_data)
    if whale_detected:
        logging.info("Whale detected! Exiting after placing order.")
        place_trade(candlestick_data, fibonacci_levels, candlestick_data['doji'].iloc[-1], whale_detected)
        return

    # Prepare data for training
    X = candlestick_data[required_columns]
    y = candlestick_data['target']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Standardize the features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train a linear regression model
    model = LinearRegression()
    model.fit(X_train_scaled, y_train)
    predictions = model.predict(X_test_scaled)

    # Log model performance
    logging.info(f"Model trained and predictions made. Accuracy: {model.score(X_test_scaled, y_test)}")









def main():
    try:
        engine = connect_to_db()
        if engine:
            logging.info("Database connection successful. Starting the Archon... ⚙️")

            steps_completed = 0  # Step counter for tracking progress
            max_steps = 10       # Prevent infinite loops by limiting iterations

            while steps_completed < max_steps:
                # Load fresh data for each loop
                candlestick_data, whale_detector_data = load_data(engine)

                if candlestick_data is None or whale_detector_data is None:
                    logging.error("Failed to load data. Skipping iteration. ⚠")
                    time.sleep(10)  # Retry after delay
                    steps_completed += 1
                    continue

                # Whale Detection
                PROCESSED_WHALES_FILE = "processed_whale_interuptions.json"
                whale_trades = detect_whale_trade(whale_detector_data)

                if whale_trades:
                    logging.info(f"Detected whale trades: {len(whale_trades)} 🐋")
                    for trade in whale_trades:
                        if isinstance(trade, dict) and 'type' in trade:
                            if trade['type'] == 'sell':
                                logging.info("Whale detected selling! Placing BUY order. 🟢")
                            elif trade['type'] == 'buy':
                                logging.info("Whale detected buying! Placing SELL order. 🔴")
                        else:
                            logging.error(f"Invalid whale trade data: {trade} ⚠")

                
                 # Calculate Fibonacci Levels
                fibonacci_levels = calculate_fibonacci_levels(candlestick_data)
                if fibonacci_levels:
                    logging.info(f"Fibonacci levels calculated successfully: {fibonacci_levels}")
                else:
                    logging.warning("Fibonacci levels calculation returned empty. ⚠")

                # Simulate trading volume calculation
                schedule_volume_calculation(candlestick_data, whale_detector_data)

                # Run the `candles.py` subprocess and capture output
                try:
                    logging.info("Starting candles.py subprocess... 🔄")
                    result = subprocess.run(
                        ["python3", "candles.py"],
                        capture_output=True,
                        text=True,
                    )

                    if result.returncode != 0:
                        logging.error(f"candles.py failed with error:\n{result.stderr}")
                    else:
                        logging.info(f"candles.py output:\n{result.stdout}")
                
                    # Log both stdout and stderr
                    logging.info(f"candles.py STDOUT: {result.stdout}")
                    if result.stderr:
                        logging.error(f"candles.py STDERR: {result.stderr}")

                except Exception as e:
                    logging.error(f"Error running candles.py subprocess: {e} ⚠")

                # Increment step counter and log progress
                steps_completed += 1
                logging.info(f"Step {steps_completed}/{max_steps} completed. Waiting for next iteration... ⏳")
                time.sleep(15)  # Adjust delay as needed

            logging.info("Bot run completed. Exiting or restarting... 🚪")

    except KeyboardInterrupt:
        logging.info("Gracefully shutting down... ❄")
    except Exception as e:
        logging.error(f"An error occurred: {e} ⚠")

if __name__ == "__main__":
    main()
