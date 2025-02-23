from flask import Flask, request, jsonify
import requests
import yaml
import jwt
import time
import secrets
import threading
from cryptography.hazmat.primitives import serialization
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import logging
import os

# Logging setup
logging.basicConfig(filename="logs.txt", level=logging.INFO, format="%(asctime)s - %(message)s")

CONFIG_FILE = "config.yaml"
CONTROLS_FILE = "controls.yaml"

# Load YAML files
def load_yaml(file_path):
    with open(file_path, "r") as f:
        return yaml.safe_load(f)

config = load_yaml(CONFIG_FILE)
controls = load_yaml(CONTROLS_FILE)

API_KEY = config["api_key"]
API_SECRET = config["api_secret"]
BASE_URL = "https://api.coinbase.com"
BASE_CURRENCY = controls.get("base_currency", "USDC")

# Flask setup
app = Flask(__name__)

def test_connection():
    """Check if the bot can connect to Coinbase API"""
    try:
        response = requests.get("https://api.coinbase.com/v2/time")
        if response.status_code == 200:
            print("✅ Internet connection and Coinbase API access are working.")
        else:
            print(f"❌ Failed to connect to Coinbase API: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"❌ Error connecting to the internet: {str(e)}")

@app.route("/", methods=["GET"])
def home():
    return "Server is running", 200

@app.route("/balances", methods=["GET"])
def get_balances():
    try:
        response = send_request("GET", "/api/v3/brokerage/accounts")
        if response:
            accounts = response.get("accounts", [])
            balances = "\n".join([ 
                f"{account.get('currency'):6}  ~${float(account.get('available_balance', {}).get('value', 0)) * get_price(account['currency'] + '-' + BASE_CURRENCY):.2f} ({account.get('available_balance', {}).get('value', 0)} {account.get('currency')})"
                for account in accounts if float(account.get('available_balance', {}).get('value', 0)) > 0
            ])
            return balances, 200
        return error_response("Failed to fetch balances")
    except Exception as e:
        return error_response(str(e))

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data or "currency" not in data or "action" not in data:
            return error_response("Invalid request format. Webhook must contain 'currency' and 'action'.")

        currency = str(data["currency"]).strip().upper()
        action = str(data["action"]).strip().upper()

        if action not in ["BUY", "SELL"]:
            return error_response("Invalid action. Must be 'BUY' or 'SELL'.")

        pair = f"{currency}-{BASE_CURRENCY}"

        price = get_price(pair)
        if not price:
            return error_response(f"Price fetch failed for {pair}")

        precision = get_precision(pair)
        min_trade, max_trade = get_trade_limits(pair)

        if action == "SELL":
            balance = get_balance(currency)
            sell_percentage = controls.get("sell_percentage", 10) / 100
            amount = Decimal(balance * sell_percentage).quantize(Decimal(precision), rounding=ROUND_DOWN)
        else:  # BUY
            base_balance = get_balance(BASE_CURRENCY)

            available_balance = base_balance * ((100 - controls.get("reserve_buffer", 50)) / 100)
            trade_amount = available_balance / controls.get("crypto_count", 1)
            amount = Decimal(trade_amount / price).quantize(Decimal(precision), rounding=ROUND_DOWN)

        if amount < min_trade:
            amount = Decimal(min_trade).quantize(Decimal(precision), rounding=ROUND_UP)

        if amount > max_trade:
            amount = Decimal(max_trade).quantize(Decimal(precision), rounding=ROUND_DOWN)

        if amount > 0:
            order_response = place_order(pair, amount, action)
            trade_value = amount * Decimal(price)
            logging.info(f"{action} {amount} {currency} (~${trade_value:.2f}) at ${price:.6f}")
            return jsonify({
                "status": f"{action} order placed for {amount} {currency} (~${trade_value:.2f})",
                "order_response": order_response
            })

        return error_response("Trade amount too small")

    except Exception as e:
        return error_response(f"Webhook error: {str(e)}")

def get_price(pair):
    response = send_request("GET", f"/v2/prices/{pair}/spot")
    if response:
        return float(response.get("data", {}).get("amount", 0))
    return None

def get_balance(currency):
    response = send_request("GET", "/api/v3/brokerage/accounts")
    if response:
        for account in response.get("accounts", []):
            if account["currency"] == currency:
                return float(account["available_balance"]["value"])
    return 0

def get_precision(pair):
    response = send_request("GET", "/api/v3/brokerage/products")
    if response and "products" in response:
        for product in response["products"]:
            if product["product_id"] == pair:
                return Decimal(str(product["base_increment"]))
    return Decimal("1E-8")

def get_trade_limits(pair):
    response = send_request("GET", "/api/v3/brokerage/products")
    if response and "products" in response:
        for product in response["products"]:
            if product["product_id"] == pair:
                return float(product['base_min_size']), float(product['base_max_size'])
    return 0.01, 999999

def place_order(pair, amount, action):
    order_data = {
        "client_order_id": secrets.token_hex(16),
        "product_id": pair,
        "side": action.upper(),
        "order_configuration": {
            "market_market_ioc": {"base_size": str(amount)}
        }
    }
    return send_request("POST", "/api/v3/brokerage/orders", order_data)

def send_request(method, path, body=None):
    try:
        jwt_token = generate_jwt(method, path)
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json"
        }
        response = requests.request(method, f"{BASE_URL}{path}", headers=headers, json=body)
        return response.json() if response.status_code == 200 else {"error": response.text}
    except Exception as e:
        return {"error": str(e)}

def generate_jwt(method, path):
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
        return None

def error_response(message):
    return jsonify({"error": message}), 400

def keep_awake():
    while True:
        try:
            requests.get("https://crypto-trading-bot-vboz.onrender.com/")
        except Exception as e:
            print(f"Keep-alive failed: {e}")
        time.sleep(300)  # 5 minutes

if __name__ == "__main__":
    test_connection()
    threading.Thread(target=keep_awake, daemon=True).start()  # Start keep-alive thread
    port = int(os.getenv("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
