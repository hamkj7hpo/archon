import psycopg2
from psycopg2 import sql
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# Database connection parameters
db_params = {
    'dbname': 'archon_data',
    'user': 'postgres',   # Adjust to your username
    'password': '!00$bMw$00!',  # Adjust to your password
    'host': 'localhost',  # Adjust if you're connecting remotely
    'port': '5432'        # Default PostgreSQL port
}

# Raydium pool address constant
RAYDIUM_POOL_ADDRESS = 'Cqt1J8ET5rxEiHEAjRGGBjgbceouMs4uDnnE634xnmK3'

# Connect to the PostgreSQL database
def connect_db():
    try:
        conn = psycopg2.connect(**db_params)
        logger.info("Connected to the database.")
        return conn
    except Exception as e:
        logger.error(f"Unable to connect to the database: {e}")
        return None

# Function to execute SQL query
def execute_sql(conn, query):
    try:
        with conn.cursor() as cursor:
            cursor.execute(query)
            conn.commit()
            logger.info("SQL query executed successfully.")
    except Exception as e:
        logger.error(f"Error executing SQL query: {e}")

def classify_and_store_critter_transactions(conn):
    query = f"""
    INSERT INTO public.whale_detector (
        whale_wallet, 
        detected_time, 
        amount, 
        token, 
        trade_type, 
        classification, 
        archon_notes
    )
    SELECT 
        v.wallet_address AS whale_wallet,  -- Wallet address
        v.block_time AS detected_time,
        v.post_balance - v.pre_balance AS amount,
        v.token_mint AS token,
        v.trade_type,
        CASE
            WHEN ABS(v.post_balance - v.pre_balance) > 1000000000 THEN '🐋'  -- Whale (1 Billion)
            WHEN ABS(v.post_balance - v.pre_balance) > 100000000 THEN '🦈'  -- Shark (100 Million)
            WHEN ABS(v.post_balance - v.pre_balance) > 10000000 THEN '🐟'   -- Fish (10 Million)
            WHEN ABS(v.post_balance - v.pre_balance) > 1000000 THEN '🐙'   -- Octopus (1 Million)
            WHEN ABS(v.post_balance - v.pre_balance) > 500000 THEN '🦀'    -- Crab (500,000)
            WHEN ABS(v.post_balance - v.pre_balance) > 100000 THEN '🦐'    -- Shrimp (100,000)
            ELSE '🐚'  -- Shell (below 100,000)
        END AS classification,
        CASE
            WHEN v.wallet_address = '{RAYDIUM_POOL_ADDRESS}' THEN 'Raydium Pool Activity'  -- Raydium pool activity
            ELSE ''  -- No specific note
        END AS archon_notes  -- Placeholder for AI-generated notes
    FROM public.validator v
    WHERE ABS(v.post_balance - v.pre_balance) > 500  -- Threshold for transaction size to consider
    ON CONFLICT (whale_wallet, detected_time)  -- Handle duplicates based on primary key
    DO UPDATE 
        SET 
            amount = EXCLUDED.amount,
            token = EXCLUDED.token,
            trade_type = EXCLUDED.trade_type,
            classification = EXCLUDED.classification,
            archon_notes = EXCLUDED.archon_notes;  -- Update all fields if duplicate
    """
    try:
        execute_sql(conn, query)
        print("Transaction classification and storage completed successfully.")
    except Exception as e:
        print(f"Error during classification and storage: {e}")




# Main function to interact with the database and run the process
def main():
    # Connect to the database
    conn = connect_db()
    if conn is None:
        logger.error("Exiting script due to failed database connection.")
        return
    
    # Call the function to classify and store transactions
    logger.info("Classifying and storing critter transactions...")
    classify_and_store_critter_transactions(conn)

    # Close the connection
    conn.close()
    logger.info("Database connection closed.")

if __name__ == "__main__":
    main()
