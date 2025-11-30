import time
import requests
import pandas as pd
import plotly.graph_objects as go

# List of tokens (add more as needed)
tokens = ["moo-deng", "ponke", "michicoin", "fartcoin"]  # Example list of tokens

# Define parameters for the CoinGecko API request
params = {
    "vs_currency": "usd",
    "days": "30"  # Fetch the last 30 days of data
}

# Loop through each token in the list
for token in tokens:
    # Construct the URL dynamically using the token name
    url = f"https://api.coingecko.com/api/v3/coins/{token}/ohlc"

    # Fetch the OHLC data
    response = requests.get(url, params=params)

    # Check for a successful response
    if response.status_code == 200:
        # Parse the JSON response
        ohlc_data = response.json()

        # Convert to DataFrame
        ohlc_df = pd.DataFrame(ohlc_data, columns=["timestamp", "open", "high", "low", "close"])
        ohlc_df["timestamp"] = pd.to_datetime(ohlc_df["timestamp"], unit='ms')

        # Save OHLC data to a file, dynamically naming the file based on the token
        file_path = f"./json_data/prices/{token}_data.json"
        ohlc_df.to_json(file_path, orient="records", indent=4)
        print(f"OHLC data saved to '{file_path}'.")

        # Plot the candlestick chart
        fig = go.Figure(data=[go.Candlestick(
            x=ohlc_df["timestamp"],
            open=ohlc_df["open"],
            high=ohlc_df["high"],
            low=ohlc_df["low"],
            close=ohlc_df["close"]
        )])

        # Customize the chart layout
        fig.update_layout(
            title=f"{token.upper()}/USD Candlestick Chart",
            xaxis_title="Date",
            yaxis_title="Price (USD)"
        )

        # Show the chart
        fig.show()
    elif response.status_code == 429:
        print(f"Rate limit exceeded for {token}. Retrying in 60 seconds...")
        time.sleep(60)  # Wait for a minute before retrying
