import requests
import yaml
import jwt
import time
import secrets
from cryptography.hazmat.primitives import serialization
from decimal import Decimal

# Load config.yaml
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

API_KEY = config["api_key"]
API_SECRET = config["api_secret"]
BASE_CURRENCY = "USDC"
BASE_URL = "https://api.coinbase.com"

def generate_jwt(method, path):
    """Generate a JWT token for Coinbase authentication."""
    try:
        uri = f"{method} api.coinbase.com{path}"
        private_key_bytes = API_SECRET.encode("utf-8")
        private_key = serialization.load_pem_private_key(private_key_bytes, password=None)
        jwt_payload = {
            "sub": API_KEY,
            "iss": "cdp",
            "nbf": int(time.time()),
            "exp": int(time.time()) + 120,
            "uri": uri,
        }
        return jwt.encode(
            jwt_payload,
            private_key,
            algorithm="ES256",
            headers={"kid": API_KEY, "nonce": secrets.token_hex()},
        )
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

def get_price(crypto):
    """Fetch the latest price of a cryptocurrency in USD."""
    url = f"{BASE_URL}/v2/prices/{crypto}-{BASE_CURRENCY}/spot"
    response = requests.get(url)
    if response.status_code == 200:
        return Decimal(response.json()["data"]["amount"])
    return Decimal(0)

def get_balances():
    """Fetch and display non-zero account balances from Coinbase."""
    path = "/api/v3/brokerage/accounts"
    jwt_token = generate_jwt("GET", path)

    if not jwt_token:
        print("Error: Unable to authenticate.")
        return

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(f"{BASE_URL}{path}", headers=headers)

    if response.status_code == 200:
        data = response.json()
        accounts = data.get("accounts", [])
        
        total_value = Decimal(0)
        balances = []

        for account in accounts:
            currency = account["currency"]
            balance = Decimal(account["available_balance"]["value"])
            
            if balance > 0:
                price = get_price(currency)
                usd_value = balance * price
                total_value += usd_value
                balances.append((usd_value, currency, balance))

        if not balances:
            print("No available balances.")
            return

        balances.sort(reverse=True, key=lambda x: x[0])  # Sort by USD value

        print("\nCoinbase Account Balances:\n")
        for usd_value, currency, balance in balances:
            print(f"${usd_value:,.2f} - {balance:,.6f} {currency}")

        print(f"\nTotal Portfolio Value: ${total_value:,.2f}\n")
    
    else:
        print(f"Error: {response.text}")

# Run the function
get_balances()
