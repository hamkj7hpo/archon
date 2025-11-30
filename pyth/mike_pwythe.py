import asyncio
import logging
from pythclient.solana import SolanaClient, SolanaPublicKey
from pythclient.pythaccounts import PythPriceAccount

logging.basicConfig(level=logging.INFO, format='%(asctime)s: %(message)s')

SOLANA_RPC = "https://mainnet.helius-rpc.com/?api-key=479f2b3d-a5e4-4fa0-b7ac-163dc4b14133"

PYTH_FEED_IDS = {
    "BONK/SOL": SolanaPublicKey("D8qK1PqRFBbL8dgwy8MZ2M4WZdNgLHNkUKEy2bMowW7X"),
    "SOL/USD": SolanaPublicKey("H6ARHf6YXhGYeQfUzQNGk6rDNQKbcKRXaP1PWDftR2t"),
}

async def mike_gets_pwythe(token_pair):
    """Mike Tyson fetches live Pyth prices for Solana meme coins!"""
    solana_client = SolanaClient(endpoint=SOLANA_RPC)
    
    price_key = PYTH_FEED_IDS.get(token_pair)
    if not price_key:
        logging.error(f"Tython thays: No Pyth feed for {token_pair}, thucker!")
        return None, None

    try:
        price_account = PythPriceAccount(key=price_key, solana=solana_client)
        await price_account.update()

        logging.info(f"Tython thays: Full Pyth account data for {token_pair}: {vars(price_account)}")

        if not price_account.aggregate_price_info:
            logging.error(f"Tython thays: Pyth data ith empty for {token_pair}, thucker!")
            return None, None

        price = price_account.aggregate_price_info.price
        confidence = price_account.aggregate_price_info.confidence

        logging.info(f"Tython thays: {token_pair} prythe ith {price:.10f} {'THOL' if 'SOL' in token_pair else 'UTHD'}! Confidenth: ±{confidence:.10f}")
        return price, confidence
    except Exception as e:
        logging.error(f"Tython thays: Pyth fetch failed, thucker! {e}")
        return None, None
    finally:
        await solana_client.close()

async def main():
    """Run Tyson’s price fetch loop for BONK!"""
    meme_coins = ["BONK/SOL", "SOL/USD"]
    
    while True:
        bonk_price = None
        sol_usd_price = None
        
        for token_pair in meme_coins:
            price, confidence = await mike_gets_pwythe(token_pair)
            if price:
                if token_pair == "BONK/SOL":
                    bonk_price = price
                elif token_pair == "SOL/USD":
                    sol_usd_price = price
        
        if bonk_price and sol_usd_price:
            bonk_usd = bonk_price * sol_usd_price
            logging.info(f"Tython thays: BONK/UTHD ith ${bonk_usd:.6f}")
        
        await asyncio.sleep(5)  # 5-second jab like archon

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Tython thays: Thop it, thucker!")
    except Exception as e:
        logging.error(f"Tython thays: Thomething broke, thucker! {e}")
