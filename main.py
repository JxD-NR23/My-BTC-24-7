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
def home(): return "Bot is running! 8-13-18-23"

@app.route('/test')
def test():
    print(">>> TEST manual solicitado", flush=True)
    job_scheduled(True)
    return "Test enviado! Revisa Telegram"

def send_text(msg):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=15)
        print(f"Telegram respuesta: {r.text}", flush=True)
    except Exception as e:
        print(f"ERROR Telegram: {e}", flush=True)

def get_price():
    try:
        return float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()["price"])
    except: return None

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()['data'][0]
        v=int(d['value']); emoji="😱" if v<25 else "😨" if v<45 else "😐" if v<55 else "🤑" if v<75 else "🤩"
        return f"{emoji} Fear & Greed {v}/100 ({d['value_classification']})"
    except: return "Sentimiento: --"

daily_start_price=None
daily_start_date=None

def job_scheduled(with_chart=False):
    global daily_start_price, daily_start_date
    print(f">>> Ejecutando job_scheduled chart={with_chart} {datetime.now(TZ)}", flush=True)
    price=get_price()
    if not price:
        print("No se pudo obtener precio", flush=True); return
    today=datetime.now(TZ).date()
    if daily_start_date!=today or daily_start_price is None:
        daily_start_date=today; daily_start_price=price
    sentiment=get_sentiment()
    chart="\n\n📈 [Ver grafico 24h](https://www.coingecko.com/en/coins/bitcoin)" if with_chart else ""
    send_text(f"₿ *BTC: ${price:,.2f}*\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España{chart}")

scheduler=BackgroundScheduler(timezone=TZ, daemon=True)
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=8, minute=0, id="btc8")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=13, minute=0, id="btc13")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=18, minute=0, id="btc18")
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=23, minute=0, id="btc23")
scheduler.start()
print("Scheduler iniciado: 8,13,18,23", flush=True)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
