import os, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()
TZ = ZoneInfo("Europe/Madrid")

print(f"--- DEBUG START ---")
print(f"TOKEN existe? {bool(TOKEN)} len={len(TOKEN)}")
print(f"CHAT_ID existe? {bool(CHAT_ID)} valor={CHAT_ID}")
print(f"--- DEBUG END ---")

app = Flask(__name__)
@app.route('/')
def home(): return "BTC Bot Live - debug"

def send_text(msg):
    if not TOKEN or not CHAT_ID:
        print("ERROR: Faltan TOKEN o CHAT_ID en Environment")
        return
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=20)
        print(f"Telegram response: {r.status_code} - {r.text[:500]}")
    except Exception as e:
        print(f"Exception enviando Telegram: {e}")

def get_price():
    try:
        j = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=15).json()
        return float(j["bitcoin"]["usd"])
    except: return None

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=15).json()['data'][0]
        return f"Fear & Greed {d['value']}/100 ({d['value_classification']})"
    except: return "Sentimiento no disponible"

daily_start_price = None
daily_start_date = None

def job_scheduled():
    global daily_start_price, daily_start_date
    price = get_price()
    if not price:
        send_text("⚠️ No pude obtener precio")
        return
    today = datetime.now(TZ).date()
    if daily_start_date!=today or daily_start_price is None:
        daily_start_date=today
        daily_start_price=price
    msg = f"₿ *BTC: ${price:,.2f}*\n{get_sentiment()}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España"
    send_text(msg)

scheduler = BackgroundScheduler(timezone=TZ)
for h in [8,13,18,23]:
    scheduler.add_job(job_scheduled, 'cron', hour=h, minute=0)
scheduler.start()

# mensaje de prueba nada mas arrancar
try:
    p = get_price()
    send_text(f"✅ *TEST BOT FUNCIONA*\nPrecio BTC ahora: ${p}\nSi ves esto, ya esta arreglado.")
except Exception as e:
    print(f"Error en arranque: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
