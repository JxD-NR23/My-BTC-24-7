import os
import requests
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# --- CONFIG ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TZ = ZoneInfo("Europe/Madrid")

daily_start_price = None
daily_start_date = None
last_alert_price = None

def send_text(msg):
    if not TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e: print(e)

def send_photo(path, caption):
    if not TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        with open(path, 'rb') as f:
            requests.post(url, data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": f}, timeout=20)
    except Exception as e: print(e)

def get_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=15)
        j = r.json()
        if "bitcoin" in j and "usd" in j["bitcoin"]:
            return float(j["bitcoin"]["usd"])
    except Exception as e: print(f"Error price: {e}")
    return None

def get_sentiment():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=15)
        data = r.json()['data'][0]
        val = data['value']
        txt = data['value_classification']
        emoji = "😱" if int(val) < 25 else "😨" if int(val) < 45 else "😐" if int(val) < 55 else "🤑" if int(val) < 75 else "🤩"
        return f"{emoji} *Fear & Greed: {val}/100* ({txt})"
    except: return "Sentimiento no disponible"

def get_chart_path():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1", timeout=20)
        prices = r.json()['prices'] # [[timestamp, price]]
        times = [datetime.fromtimestamp(p[0]/1000, tz=TZ) for p in prices]
        vals = [p[1] for p in prices]

        plt.figure(figsize=(8,3.5))
        plt.plot(times, vals)
        plt.title("BTC últimas 24h (USD)")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        path = "/tmp/btc.png"
        plt.savefig(path, dpi=150)
        plt.close()
        return path
    except Exception as e:
        print(f"Chart error: {e}")
        return None

def job_scheduled(with_chart=False):
    global daily_start_price, daily_start_date
    price = get_price()
    if not price:
        send_text("⚠️ No pude obtener precio BTC ahora")
        return

    # Inicializar precio del día a las 00:00 España
    today = datetime.now(TZ).date()
    if daily_start_date!= today or daily_start_price is None:
        daily_start_date = today
        daily_start_price = price
        print(f"Nuevo día {today}, precio inicio: {price}")

    sentiment = get_sentiment()
    msg = f"₿ *BTC: ${price:,.2f}*\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España"

    if with_chart:
        chart = get_chart_path()
        if chart:
            send_photo(chart, msg)
        else:
            send_text(msg)
    else:
        send_text(msg)

def job_check_10pct():
    global daily_start_price, daily_start_date, last_alert_price
    price = get_price()
    if not price or not daily_start_price: return

    today = datetime.now(TZ).date()
    if daily_start_date!= today: return # se resetea en el job principal

    change = ((price - daily_start_price) / daily_start_price) * 100

    # Evitar spam: solo alerta si cambia mucho desde la última alerta
    if abs(change) >= 10:
        if last_alert_price is None or abs((price - last_alert_price)/last_alert_price*100) >= 2:
            direction = "🚀 SUBIDA" if change > 0 else "📉 CAÍDA"
            send_text(f"🚨 *ALERTA {direction} 10%* 🚨\n\nPrecio inicio día: ${daily_start_price:,.2f}\nPrecio ahora: ${price:,.2f}\nVariación: *{change:+.2f}%*")
            last_alert_price = price

# --- SCHEDULER ---
scheduler = BackgroundScheduler(timezone=TZ)
# Precio + sentimiento
for h in [8,13,18,23]:
    scheduler.add_job(lambda h=h: job_scheduled(with_chart=(h in [8,23])), 'cron', hour=h, minute=0)
# Check 10% cada 5 min
scheduler.add_job(job_check_10pct, 'interval', minutes=5)
scheduler.start()

# --- FLASK para Render ---
app = Flask(__name__)
@app.route('/')
def home(): return "BTC Bot 24/7 OK"

if __name__ == "__main__":
    job_scheduled(with_chart=False) # Mensaje de arranque
    send_text("✅ Bot configurado: avisos 8h,13h,18h,23h + gráfico 8h y 23h + alerta 10% diaria")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
