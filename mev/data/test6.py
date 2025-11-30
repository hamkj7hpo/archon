import psycopg2
from datetime import datetime

# Database connection parameters
DB_PARAMS = {
    "dbname": "archon_data",
    "user": "postgres",
    "password": "!00$bMw$00!",
    "host": "localhost",
    "port": "5432"
}

# Sample transaction data (manually created for testing)
test_data = {
    "transaction_hash": "sample_hash_123",
    "block_time": datetime.utcnow().isoformat(),
    "wallet_address": "sample_wallet_address_456",
    "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "pre_balance": 100.0,
    "post_balance": 200.0,
    "trade_type": "buy"
}

# Database insertion function
def insert_into_db(data):
    """
    Inserts transaction data into the database.
    """
    try:
        connection = psycopg2.connect(**DB_PARAMS)
        cursor = connection.cursor()
        query = """
            INSERT INTO validator (transaction_hash, block_time, wallet_address, token_mint, pre_balance, post_balance, trade_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (transaction_hash) DO NOTHING;
        """
        
        # Debugging log to check data
        print(f"Inserting into database: {data}")
        
        cursor.execute(query, (
            data['transaction_hash'],
            data['block_time'],
            data['wallet_address'],
            data['token_mint'],
            data['pre_balance'],
            data['post_balance'],
            data['trade_type']
        ))
        
        connection.commit()  # Committing the changes
        
        # Check if any rows were inserted
        if cursor.rowcount > 0:
            print("Data inserted successfully!")
        else:
            print("No data inserted (duplicate or empty data).")
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        if connection:
            cursor.close()
            connection.close()

# Test the function by inserting the sample data
insert_into_db(test_data)
