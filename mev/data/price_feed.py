import requests
import json
from datetime import datetime, timedelta
import pytz
import time
import subprocess  # For running external scripts

# Define the token name (CoinGecko uses 'bonk' as the token ID)
token_id = "bonk"  # Bonk token on CoinGecko
url = f"https://api.coingecko.com/api/v3/coins/{token_id}/ohlc"

# Global list to store the OHLC data
ohlc_data = []

def fetch_market_data():
    """
    Fetch hourly market data from CoinGecko API for the given token.
    """
    params = {
        "vs_currency": "usd",
        "days": "1",  # Fetch the last 1 day of data (1-hour candles)
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        print("Error fetching data:", response.status_code)
        return None

def fetch_usd_sol_rate():
    """
    Fetch the USD/SOL exchange rate.
    """
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
        response.raise_for_status()
        data = response.json()
        return data["solana"]["usd"]
    except Exception as e:
        print(f"Error fetching USD/SOL rate: {e}")
        return None

def process_hourly_data(hourly_data, usd_sol_rate):
    """
    Process 1-hour OHLC data and append it to the global list, converting prices to Lamports.
    """
    global ohlc_data
    lamports_per_sol = 1_000_000_000  # 1 SOL = 1,000,000,000 lamports
    usd_to_lamports = lamports_per_sol / usd_sol_rate  # Conversion factor for 1 USD to lamports

    la_timezone = pytz.timezone('America/Los_Angeles')  # Set LA time zone
    for entry in hourly_data:
        if len(entry) == 5:  # If volume is not available
            timestamp, open_price, high_price, low_price, close_price = entry
        else:
            continue  # Skip any unexpected data entries
        
        # Convert USD prices to Lamports
        open_price = int(round(open_price * usd_to_lamports))
        high_price = int(round(high_price * usd_to_lamports))
        low_price = int(round(low_price * usd_to_lamports))
        close_price = int(round(close_price * usd_to_lamports))

        timestamp_utc = datetime.utcfromtimestamp(timestamp / 1000)  # Convert ms to seconds
        timestamp_la = timestamp_utc.replace(tzinfo=pytz.utc).astimezone(la_timezone)  # Convert to LA timezone
        
        # Append the hourly data to the list if it's new
        if not ohlc_data or ohlc_data[-1]['timestamp'] != timestamp_la:
            ohlc_entry = {
                'timestamp': timestamp_la.strftime('%Y-%m-%d %H:%M:%S'),  # Format the time as a string
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price
            }
            ohlc_data.append(ohlc_entry)

def save_data_to_json(file_name, data):
    """
    Save the given data to a JSON file.
    """
    file_path = f'./json_data/ohlc/{file_name}'
    with open(file_path, 'w') as f:
        json.dump(data, f, default=str, indent=4)  # Using default=str to handle datetime serialization
    print(f"Data saved to {file_path}")

def wait_for_next_request():
    """
    Calculate the time until the next request and wait.
    """
    now = datetime.now(pytz.timezone('America/Los_Angeles'))
    
    # Calculate the next request times (on the hour + 1min or half hour + 1min)
    if now.minute < 30:
        next_request_time = now.replace(minute=1, second=0, microsecond=0)
    else:
        next_request_time = now.replace(minute=31, second=0, microsecond=0)
    
    if next_request_time < now:
        next_request_time += timedelta(minutes=30)

    wait_time = (next_request_time - now).total_seconds()
    print(f"Waiting for {wait_time} seconds until {next_request_time.strftime('%Y-%m-%d %H:%M:%S')}")
    time.sleep(wait_time)

def main():
    """
    Main function to fetch, process, and save data periodically every half hour.
    """
    while True:
        wait_for_next_request()
        
        # Fetch USD/SOL rate
        usd_sol_rate = fetch_usd_sol_rate()
        if usd_sol_rate is None:
            continue  # Skip processing if rate fetch failed
        
        # Fetch market data
        market_data = fetch_market_data()
        if market_data:
            process_hourly_data(market_data, usd_sol_rate)
            save_data_to_json("bonk_candles.json", ohlc_data)
        
        # Run the price analyzer script and print output to the terminal
        result = subprocess.run(["python3", "price_analyzer.py"], capture_output=True, text=True)
        print(result.stdout)

        

if __name__ == "__main__":
    main()
