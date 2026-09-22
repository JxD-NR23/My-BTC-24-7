import os, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()
TZ = ZoneInfo("Europe/Madrid")

app = Flask(__name__)
@app.route('/')
def home(): return "BTC Bot 24/7 OK"

def send_text(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e: print(e)

def get_price():
    # Intento 1: Binance (el que nunca falla en Render)
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()
        return float(r["price"])
    except: pass
    # Intento 2: Coinbase
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=10).json()
        return float(r["data"]["amount"])
    except: pass
    # Intento 3: CoinGecko
    try:
        j = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10).json()
        return float(j["bitcoin"]["usd"])
    except: return None

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()['data'][0]
        v = int(d['value'])
        emoji = "😱" if v<25 else "😨" if v<45 else "😐" if v<55 else "🤑" if v<75 else "🤩"
        return f"{emoji} Fear & Greed {v}/100 ({d['value_classification']})"
    except: return "Sentimiento: --"

daily_start_price = None
daily_start_date = None
last_alert_price = None

def job_scheduled(with_chart=False):
    global daily_start_price, daily_start_date
    price = get_price()
    if not price: return
    today = datetime.now(TZ).date()
    if daily_start_date!= today or daily_start_price is None:
        daily_start_date = today
        daily_start_price = price
    sentiment = get_sentiment()
    chart = "\n\n📈 [Ver gráfico 24h](https://www.coingecko.com/en/coins/bitcoin)" if with_chart else ""
    msg = f"₿ *BTC: ${price:,.2f}*\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España{chart}"
    send_text(msg)

def job_check_10pct():
    global last_alert_price
    price = get_price()
    if not price or not daily_start_price: return
    change = ((price - daily_start_price)/daily_start_price)*100
    if abs(change) >= 10:
        if last_alert_price is None or abs((price-last_alert_price)/last_alert_price*100) >= 2:
            send_text(f"🚨 *{'🚀 SUBIDA' if change>0 else '📉 CAIDA'} {change:+.1f}% HOY* 🚨\nInicio: ${daily_start_price:,.2f}\nAhora: ${price:,.2f}")
            last_alert_price = price

scheduler = BackgroundScheduler(timezone=TZ)
for h in [8,13,18,23]:
    scheduler.add_job(lambda h=h: job_scheduled(with_chart=(h in [8][23])), 'cron', hour=h, minute=0)
scheduler.add_job(job_check_10pct, 'interval', minutes=5)
scheduler.start()

# Mensaje inicial
p = get_price()
if p:
    send_text(f"✅ *Bot BTC 24/7 FINAL - YA FUNCIONA*\nPrecio: ${p:,.2f}\n\nHorarios fijos: 8h,13h,18h,23h (España)\nGráfico: 8h y 23h\nAlerta 10% diaria cada 5min")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
