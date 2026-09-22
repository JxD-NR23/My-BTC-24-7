import os, requests, io, pytz
from datetime import datetime
from flask import Flask
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from telegram import Bot
from apscheduler.schedulers.background import BackgroundScheduler

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=TOKEN)
app = Flask(__name__)
MADRID = pytz.timezone("Europe/Madrid")
daily_open_price = None

def get_price():
    return requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd").json()["bitcoin"]["usd"]

def get_sentiment():
    d = requests.get("https://api.alternative.me/fng/?limit=1").json()["data"][0]
    return f"{d['value']}/100 ({d['value_classification']})"

def get_chart():
    data = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1").json()
    prices = [p[1] for p in data["prices"]]
    plt.figure()
    plt.plot(prices)
    plt.title("Bitcoin 24h")
    plt.ylabel("USD")
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

def send(with_chart=False):
    try:
        price = get_price()
        senti = get_sentiment()
        msg = f"₿ BTC: ${price:,.2f}\n📊 Sentimiento: {senti}\n🕒 {datetime.now(MADRID).strftime('%d/%m %H:%M')} España"
        if with_chart:
            bot.send_photo(chat_id=CHAT_ID, photo=get_chart(), caption=msg, parse_mode="Markdown")
        else:
            bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        print(e)

def check_10():
    global daily_open_price
    try:
        price = get_price()
        now = datetime.now(MADRID)
        if daily_open_price is None:
            daily_open_price = price
            return
        if now.hour == 0 and now.minute < 10:
            daily_open_price = price
            return
        change = ((price - daily_open_price) / daily_open_price) * 100
        if abs(change) >= 10:
            bot.send_message(chat_id=CHAT_ID, text=f"🚨 ALERTA {change:.2f}% 🚨\nBTC: ${price:,.2f}\nApertura hoy: ${daily_open_price:,.2f}")
            daily_open_price = price
    except Exception as e:
        print(e)

sched = BackgroundScheduler(timezone=MADRID)
sched.add_job(lambda: send(True), 'cron', hour=8, minute=0)
sched.add_job(lambda: send(False), 'cron', hour=13, minute=0)
sched.add_job(lambda: send(False), 'cron', hour=18, minute=0)
sched.add_job(lambda: send(True), 'cron', hour=23, minute=0)
sched.add_job(check_10, 'interval', minutes=5)
sched.start()

@app.route("/")
def home(): return "Bot OK 24/7"

if __name__ == "__main__":
    daily_open_price = get_price()
    app.run(host="0.0.0.0", port=8000)
