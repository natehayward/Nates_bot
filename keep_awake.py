import time
import requests

URL = "https://crypto-trading-bot-vboz.onrender.com/"  # Update if needed

while True:
    try:
        response = requests.get(URL)
        print(f"Pinged {URL}, Status: {response.status_code}")
    except Exception as e:
        print(f"Ping failed: {e}")
    time.sleep(300)  # Ping every 5 minutes
