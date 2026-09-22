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
def home():
    return f"Bot is running! Token OK: {bool(TOKEN)} Chat OK: {bool(CHAT_ID)}"

@app.route('/test')
def test():
    print(">>> TEST recibido - intentando enviar", flush=True)
    print(f">>> TOKEN existe: {bool(TOKEN)} CHAT_ID existe: {bool(CHAT_ID)}", flush=True)
    job_scheduled(True)
    return "Test enviado! Mira los Logs de Render y Telegram"

def send_text(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        print(f">>> Enviando a Telegram: {url[:50]}...", flush=True)
        r = requests.post(url,
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=20)
        print(f">>> Telegram status {r.status_code} respuesta: {r.text[:500]}", flush=True)
        return True
    except Exception as e:
        print(f">>> ERROR Telegram EXCEPCION: {e}", flush=True)
        return False

def get_price():
    # Intento 1: CoinGecko (no bloquea Render)
    try:
        j = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=15).json()
        p = float(j["bitcoin"]["usd"])
        print(f">>> Precio CoinGecko OK: {p}", flush=True)
        return p
    except Exception as e:
        print(f">>> Error CoinGecko: {e}", flush=True)
    # Intento 2: Kraken
    try:
        j = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=15).json()
        p = float(j["result"]["XXBTZUSD"]["c"][0])
        print(f">>> Precio Kraken OK: {p}", flush=True)
        return p
    except Exception as e:
        print(f">>> Error Kraken: {e}", flush=True)
    return None

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()['data'][0]
        v=int(d['value']); emoji="😱" if v<25 else "😨" if v<45 else "😐" if v<55 else "🤑" if v<75 else "🤩"
        return f"{emoji} Fear & Greed {v}/100 ({d['value_classification']})"
    except: return "Sentimiento: --"

def job_scheduled(with_chart=False):
    print(f">>> job_scheduled INICIADO chart={with_chart} {datetime.now(TZ)}", flush=True)
    price=get_price()
    if not price:
        print(">>> Fallo total obteniendo precio, envio mensaje de error", flush=True)
        send_text("⚠️ Bot BTC: no pude obtener el precio (API caida)")
        return
    sentiment=get_sentiment()
    chart="\n\n📈 [Ver grafico 24h](https://www.coingecko.com/en/coins/bitcoin)" if with_chart else ""
    msg = f"₿ *BTC: ${price:,.2f}*\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España{chart}"
    send_text(msg)

scheduler=BackgroundScheduler(timezone=TZ, daemon=True)
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=8, minute=0, id="btc8")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=13, minute=0, id="btc13")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=18, minute=0, id="btc18")
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=23, minute=0, id="btc23")
scheduler.start()
print(">>> Scheduler iniciado OK: 8,13,18,23", flush=True)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
