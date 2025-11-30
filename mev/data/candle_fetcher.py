import requests
import pandas as pd
from psycopg2.extras import execute_values
import psycopg2
from datetime import datetime, timedelta

# Fetch the USD/SOL exchange rate
def fetch_usd_sol_rate():
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
        response.raise_for_status()
        data = response.json()
        return data["solana"]["usd"]
    except Exception as e:
        print(f"Error fetching USD/SOL rate: {e}")
        return None

# Convert prices to lamports using USD/SOL rate
def convert_to_lamports(df, usd_sol_rate):
    if usd_sol_rate is None:
        raise ValueError("USD/SOL rate is required for conversion to lamports.")
    lamports_per_sol = 1_000_000_000  # 1 SOL = 1,000,000,000 lamports
    usd_to_lamports = lamports_per_sol / usd_sol_rate  # Conversion factor for 1 USD to lamports
    df[["open", "high", "low", "close"]] = (df[["open", "high", "low", "close"]] * usd_to_lamports).astype(int)
    return df

# Fetch OHLC data
def fetch_ohlc_data(token, days):
    url = f"https://api.coingecko.com/api/v3/coins/{token}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        ohlc_data = response.json()
        df = pd.DataFrame(ohlc_data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
        return df
    except Exception as e:
        print(f"Failed to fetch data for {token}. Error: {e}")
        return None

# Insert data into the database with converted values
def insert_data_to_db(df, conn, token_pair):
    usd_sol_rate = fetch_usd_sol_rate()  # Get the current USD/SOL rate
    if usd_sol_rate is None:
        raise ValueError("Failed to fetch USD/SOL rate. Cannot proceed with data insertion.")
    # Convert all price-related fields to lamports
    df = convert_to_lamports(df, usd_sol_rate)
    with conn.cursor() as cursor:
        records = df.to_dict(orient="records")
        execute_values(cursor, """
            INSERT INTO candlestick_data (
                timestamp, open, high, low, close, ma_10, ma_50, doji, bullish_engulfing, bearish_engulfing, token_pair
            ) VALUES %s
            ON CONFLICT (timestamp, token_pair)
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                ma_10 = EXCLUDED.ma_10,
                ma_50 = EXCLUDED.ma_50,
                doji = EXCLUDED.doji,
                bullish_engulfing = EXCLUDED.bullish_engulfing,
                bearish_engulfing = EXCLUDED.bearish_engulfing;
        """, [
            (row["timestamp"], row["open"], row["high"], row["low"], row["close"], 
             row.get("ma_10"), row.get("ma_50"), row.get("doji"), 
             row.get("bullish_engulfing"), row.get("bearish_engulfing"), token_pair)
            for row in records
        ])
        conn.commit()
        print(f"Inserted/updated {len(df)} rows for {token_pair}.")

# Main execution
if __name__ == "__main__":
    token = "bonk"  # Replace with the desired token
    token_pair = "bonk-usd"
    days = 30  # Adjust as needed

    # Database connection
    conn = psycopg2.connect(
        dbname="archon_data",
        user="postgres",
        password="!00$bMw$00!",
        host="localhost",
        port="5432"
    )

    try:
        print(f"No existing data for {token_pair}. Fetching new data...")
        ohlc_df = fetch_ohlc_data(token, days)
        if ohlc_df is not None:
            insert_data_to_db(ohlc_df, conn, token_pair)
        else:
            print(f"Failed to fetch OHLC data for {token}.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

