import psycopg2
import time

def fetch_data():
    conn = psycopg2.connect(dbname="archon_data", user="postgres", password="!00$bMw$00!", host="localhost")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM validator ORDER BY block_time ASC;")
    result = cursor.fetchall()
    for row in result:
        print(row)

    cursor.close()
    conn.close()

# Poll every 5 seconds
while True:
    fetch_data()
    time.sleep(5)  # wait 5 seconds before checking again
