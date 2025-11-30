import pandas as pd
import psycopg2
from datetime import datetime
from decimal import Decimal

TOKEN_PAIR = "BjZKz1z4UMjJPvPfKwTwjPErVBWnewnJFvcZB6minymy"


# Function to load data
def load_data(file_path):
    """Load historical price data from a JSON file."""
    data = pd.read_json(file_path)
    data['timestamp'] = pd.to_datetime(data['timestamp'])  # Ensure correct timestamp format
    return data

# Function to format numerical prices to 8 decimal places as strings
def format_prices(data):
    """Format price data to 8 decimal places as strings."""
    data['open'] = data['open'].apply(lambda x: f'{x:.8f}')
    data['high'] = data['high'].apply(lambda x: f'{x:.8f}')
    data['low'] = data['low'].apply(lambda x: f'{x:.8f}')
    data['close'] = data['close'].apply(lambda x: f'{x:.8f}')
    return data


# Function to calculate moving averages
def calculate_moving_averages(data, periods):
    """Add moving averages to the DataFrame."""
    for period in periods:
        data[f'ma_{period}'] = data['close'].rolling(window=period).mean()
    return data

# Function to identify doji candlestick pattern
def identify_doji(data, threshold=0.1):
    """Identify doji candlestick patterns."""
    
    # Convert columns to numeric, handling errors if any
    data['open'] = pd.to_numeric(data['open'], errors='coerce')
    data['close'] = pd.to_numeric(data['close'], errors='coerce')
    data['high'] = pd.to_numeric(data['high'], errors='coerce')
    data['low'] = pd.to_numeric(data['low'], errors='coerce')

    # Print data types to ensure conversion
    print(f"Data types: {data.dtypes}")
    
    # Now perform the calculation for Doji
    data['doji'] = (abs(data['open'] - data['close']) / (data['high'] - data['low']) < threshold)
    data['doji'] = data['doji'].fillna(False)
    return data

# Function to identify engulfing pattern
def identify_engulfing(data):
    """Identify bullish and bearish engulfing patterns."""
    data['bullish_engulfing'] = (
        (data['close'] > data['open']) &
        (data['close'].shift(1) < data['open'].shift(1)) &
        (data['open'] < data['close'].shift(1)) &
        (data['close'] > data['open'].shift(1))
    )

    data['bearish_engulfing'] = (
        (data['close'] < data['open']) &
        (data['close'].shift(1) > data['open'].shift(1)) &
        (data['open'] > data['close'].shift(1)) &
        (data['close'] < data['open'].shift(1))
    )

    # Ensure no NaN values in boolean columns
    data['bullish_engulfing'] = data['bullish_engulfing'].fillna(False)
    data['bearish_engulfing'] = data['bearish_engulfing'].fillna(False)
    return data

# Function to insert data into the database
def insert_data_to_db(data, conn):
    """Insert processed data into the PostgreSQL database."""
    cursor = conn.cursor()

    for index, row in data.iterrows():
        # First, delete any existing data for the given timestamp
        cursor.execute("""
            DELETE FROM candlestick_data
            WHERE timestamp = %s
            """, (row['timestamp'],))

        # Format numerical values to fixed-point notation (as strings with 8 decimal places)
        formatted_row = {
            'timestamp': row['timestamp'],
            'open': '{:.8f}'.format(float(row['open'])),
            'high': '{:.8f}'.format(float(row['high'])),
            'low': '{:.8f}'.format(float(row['low'])),
            'close': '{:.8f}'.format(float(row['close'])),
            'ma_10': '{:.8f}'.format(float(row['ma_10'])) if not pd.isna(row['ma_10']) else None,
            'ma_50': '{:.8f}'.format(float(row['ma_50'])) if not pd.isna(row['ma_50']) else None,
            'doji': row['doji'],
            'bullish_engulfing': row['bullish_engulfing'],
            'bearish_engulfing': row['bearish_engulfing'],
            'token_pair': TOKEN_PAIR  # Add the token pair here
        }

        # Then, insert the new data into the table
        cursor.execute("""
            INSERT INTO candlestick_data (
                timestamp, open, high, low, close, ma_10, ma_50, doji, bullish_engulfing, bearish_engulfing, token_pair
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                formatted_row['timestamp'], 
                formatted_row['open'], 
                formatted_row['high'], 
                formatted_row['low'], 
                formatted_row['close'],
                formatted_row['ma_10'], 
                formatted_row['ma_50'], 
                formatted_row['doji'], 
                formatted_row['bullish_engulfing'], 
                formatted_row['bearish_engulfing'],
                formatted_row['token_pair']  # Insert the token pair value
            ))

    # Commit and close the cursor
    conn.commit()
    cursor.close()


# Main script
if __name__ == "__main__":
    file_path = "json_data/ohlc/bonk_candles.json"  # Replace with your file path
    data = load_data(file_path)

    # Format numerical values to 8 decimal places as strings
    data = format_prices(data)
    
    # Calculate moving averages
    moving_averages = ["ma_10", "ma_50"]
    data = calculate_moving_averages(data, periods=[10, 50])
    
    # Ensure no NaN in moving averages
    data['ma_10'] = data['ma_10'].fillna(0)
    data['ma_50'] = data['ma_50'].fillna(0)

    # Identify candlestick patterns
    data = identify_doji(data)
    data = identify_engulfing(data)

    # Print rows with detected patterns
    print("Doji patterns:")
    print(data[data['doji']])

    print("Bullish engulfing patterns:")
    print(data[data['bullish_engulfing']])

    print("Bearish engulfing patterns:")
    print(data[data['bearish_engulfing']])

    print(data[['open', 'high', 'low', 'close']].head())


    # Connect to PostgreSQL database
    try:
        conn = psycopg2.connect(
            dbname="archon_data",  # Database name
            user="postgres",       # Database user
            password="!00$bMw$00!",  # Database password
            host="localhost",      # Database host
            port="5432"            # Database port
        )
        
        # Insert the processed data into the database
        insert_data_to_db(data, conn)
        print("Data inserted successfully into the database.")

    except Exception as e:
        print("Error connecting to database:", e)
    
    finally:
        if conn:
            conn.close()  # Close the database connection
