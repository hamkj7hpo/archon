import requests
import pandas as pd

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

# Fetch the BONK/USD exchange rate
def fetch_bonk_usd_rate():
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bonk&vs_currencies=usd")
        response.raise_for_status()
        data = response.json()
        return data["bonk"]["usd"]
    except Exception as e:
        print(f"Error fetching BONK/USD rate: {e}")
        return None

# Convert BONK prices to lamports using USD/SOL rate
def convert_bonk_to_lamports(bonk_usd_price, usd_sol_rate):
    if bonk_usd_price is None or usd_sol_rate is None:
        raise ValueError("Both BONK/USD and USD/SOL rates are required for conversion to lamports.")
    lamports_per_sol = 1_000_000_000  # 1 SOL = 1,000,000,000 lamports
    usd_to_lamports = lamports_per_sol / usd_sol_rate  # Conversion factor for 1 USD to lamports
    bonk_price_in_lamports = bonk_usd_price * usd_to_lamports
    return bonk_price_in_lamports

# Example usage
def main():
    usd_sol_rate = fetch_usd_sol_rate()
    bonk_usd_rate = fetch_bonk_usd_rate()

    if usd_sol_rate and bonk_usd_rate:
        bonk_price_in_lamports = convert_bonk_to_lamports(bonk_usd_rate, usd_sol_rate)
        print(f"BONK price in Lamports: {bonk_price_in_lamports}")
    else:
        print("Failed to fetch necessary exchange rates.")

if __name__ == "__main__":
    main()
