import json

# Path to the JSON file
input_file = 'json_data/transactions/bonk_tx.json'
output_file = 'json_data/transactions/bonk_tx_filtered.json'

def remove_duplicates(input_path, output_path):
    try:
        # Load the data
        with open(input_path, 'r') as file:
            data = json.load(file)
        
        # Use a dictionary to remove duplicates
        unique_transactions = {}
        for entry in data:
            tx_id = entry['transaction_id']
            if tx_id not in unique_transactions:
                unique_transactions[tx_id] = entry

        # Convert back to a list
        filtered_data = list(unique_transactions.values())

        # Save the filtered data
        with open(output_path, 'w') as file:
            json.dump(filtered_data, file, indent=4)
        
        print(f"Removed duplicates. Original count: {len(data)}, Filtered count: {len(filtered_data)}")
    
    except Exception as e:
        print(f"Error: {e}")

# Execute the function
remove_duplicates(input_file, output_file)
