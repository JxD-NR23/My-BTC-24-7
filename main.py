import os
import time
import requests
import threading
from flask import Flask

# --- CONFIG ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Falta TELEGRAM_TOKEN o CHAT_ID en Environment")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

def get_btc_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10)
        data = r.json()
        # Aquí está el arreglo del error 'bitcoin'
        if "bitcoin" in data and "usd" in data["bitcoin"]:
            return data["bitcoin"]["usd"]
        else:
            print(f"API rara: {data}")
            return None
    except Exception as e:
        print(f"Error precio: {e}")
        return None

def bot_loop():
    send_telegram("🚀 Bot BTC 24/7 INICIADO en Render - todo OK")
    while True:
        price = get_btc_price()
        if price:
            print(f"BTC: {price}")
            # Aquí puedes poner tu lógica de alertas
            # Ejemplo: si baja de 60000 te avisa
            # if price < 60000: send_telegram(f"⚠️ BTC bajó a {price}")
        time.sleep(60) # revisa cada 60 seg

# --- Servidor web para que Render no lo apague ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot BTC activo 24/7"

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    # Render necesita un puerto
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
