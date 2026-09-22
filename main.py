import os, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TZ = ZoneInfo("Europe/Madrid")

daily_start_price = None
daily_start_date = None
last_alert_price = None

app = Flask(__name__)
@app.route('/')
def home():
    return "BTC Bot 24/7 OK"

def send_text(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(e)

def get_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=15).json()
        return float(r["bitcoin"]["usd"])
    except:
        return None

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=15).json()['data'][0]
        v = int(d['value'])
        emoji = "😱" if v < 25 else "😨" if v < 45 else "😐" if v < 55 else "🤑" if v < 75 else "🤩"
        return f"{emoji} *Fear & Greed {v}/100* ({d['value_classification']})"
    except:
        return "Sentimiento no disponible"

def job_scheduled(with_chart=False):
    global daily_start_price, daily_start_date
    price = get_price()
    if not price:
        send_text("⚠️ No pude obtener precio BTC ahora")
        return
    today = datetime.now(TZ).date()
    if daily_start_date!= today or daily_start_price is None:
        daily_start_date = today
        daily_start_price = price

    sentiment = get_sentiment()
    base_msg = f"₿ *BTC: ${price:,.2f}*\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España"

    if with_chart:
        # Sin matplotlib, mandamos grafico via imagen de Coingecko + link
        msg = base_msg + "\n\n📈 [Ver gráfico 24h](https://www.coingecko.com/en/coins/bitcoin)"
        # Enviamos foto del sparkline de Coingecko
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                json={"chat_id": CHAT_ID, "photo": "https://www.coingecko.com/coins/1/sparkline.svg", "caption": msg, "parse_mode": "Markdown"}, timeout=15)
        except:
            send_text(msg)
    else:
        send_text(base_msg)

def job_check_10pct():
    global last_alert_price
    price = get_price()
    if not price or not daily_start_price:
        return
    change = ((price - daily_start_price) / daily_start_price) * 100
    if abs(change) >= 10:
        if last_alert_price is None or abs((price-last_alert_price)/last_alert_price*100) >= 2:
            send_text(f"🚨 *ALERTA {'🚀 SUBIDA' if change>0 else '📉 CAÍDA'} {change:+.1f}% HOY* 🚨\nInicio: ${daily_start_price:,.2f}\nAhora: ${price:,.2f}")
            last_alert_price = price

scheduler = BackgroundScheduler(timezone=TZ)
for h in [8,13,18,23]:
    scheduler.add_job(lambda h=h: job_scheduled(with_chart=(h in [8,23])), 'cron', hour=h, minute=0)
scheduler.add_job(job_check_10pct, 'interval', minutes=5)
scheduler.start()

# Mensaje de arranque
try:
    p = get_price()
    send_text(f"✅ *Bot BTC 24/7 RE-ACTIVADO*\nPrecio ahora: ${p:,.2f} \nHorarios: 8h,13h,18h,23h (España)\nGráfico: 8h y 23h\nAlerta: +-10% diaria\n\nYa no fallará el deploy.")
except:
    pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
