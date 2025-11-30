import requests
try:
    response = requests.get("https://50.62.182.123:8000/data", timeout=5, verify=False)
    print(response.json())
except Exception as e:
    print(f"Error: {e}")
