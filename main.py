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
def home(): return "Bot is running!"
@app.route('/test')
def test():
    job_scheduled(True)
    return "Test enviado!"

def send_text(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=15)

def get_price():
    try: return float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=10).json()["price"])
    except: return None

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()['data'][0]
        v=int(d['value'])
        emoji="😱" if v<25 else "😨" if v<45 else "😐" if v<55 else "🤑" if v<75 else "🤩"
        return f"{emoji} Fear & Greed {v}/100 ({d['value_classification']})"
    except: return "Sentimiento: --"

daily_start_price=None
daily_start_date=None

def job_scheduled(with_chart=False):
    global daily_start_price, daily_start_date
    price=get_price()
    if not price: return
    today=datetime.now(TZ).date()
    if daily_start_date!=today or daily_start_price is None:
        daily_start_date=today
        daily_start_price=price
    sentiment=get_sentiment()
    chart="\n\n📈 [Ver grafico 24h](https://www.coingecko.com/en/coins/bitcoin)" if with_chart else ""
    send_text(f"₿ *BTC: ${price:,.2f}*\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España{chart}")

scheduler=BackgroundScheduler(timezone=TZ)
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=8, minute=0)
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=13, minute=0)
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=18, minute=0)
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=23, minute=0)
scheduler.start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
