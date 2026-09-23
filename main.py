import os, requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request # NUEVO: añadido request para escuchar
from apscheduler.schedulers.background import BackgroundScheduler
import matplotlib # NUEVO
matplotlib.use('Agg') # NUEVO: para dibujar sin pantalla en Render
import matplotlib.pyplot as plt # NUEVO

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

def send_text(msg, chat_id=None): # NUEVO: ahora acepta chat_id para responder a quien escribe
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        print(f">>> Enviando a Telegram: {url[:50]}...", flush=True)
        r = requests.post(url,
            json={"chat_id": chat_id or CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=20)
        print(f">>> Telegram status {r.status_code} respuesta: {r.text[:500]}", flush=True)
        return True
    except Exception as e:
        print(f">>> ERROR Telegram EXCEPCION: {e}", flush=True)
        return False

# NUEVO: funcion para mandar foto del grafico
def send_photo(photo_path, caption="", chat_id=None):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as f:
            r = requests.post(url, data={"chat_id": chat_id or CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": f}, timeout=30)
        print(f">>> Foto enviada status {r.status_code}", flush=True)
    except Exception as e:
        print(f">>> Error foto: {e}", flush=True)

def get_price():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
        j = requests.get(url, timeout=15, headers=headers).json()
        p = float(j["bitcoin"]["usd"])
        ch = float(j["bitcoin"].get("usd_24h_change", 0))
        print(f">>> CoinGecko OK: {p} {ch:.2f}%", flush=True)
        return p, ch
    except Exception as e:
        print(f">>> Error CoinGecko: {e}", flush=True)
    try:
        j = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=15).json()
        p = float(j["result"]["XXBTZUSD"]["c"][0])
        return p, 0.0
    except Exception as e:
        print(f">>> Error Kraken: {e}", flush=True)
    return None, 0.0

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()['data'][0]
        v=int(d['value']); emoji="😱" if v<25 else "😨" if v<45 else "😐" if v<55 else "🤑" if v<75 else "🤩"
        return f"{emoji} Fear & Greed {v}/100 ({d['value_classification']})"
    except: return "Sentimiento: --"

# NUEVO: genera imagen real de velas
def build_chart_image():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        # Intento 1: velas
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days=1"
        r = requests.get(url, timeout=15, headers=headers)
        data = r.json()
        if isinstance(data, list) and len(data) > 5:
            times = [datetime.fromtimestamp(x[0]/1000, tz=TZ) for x in data]
            opens = [x[1] for x in data]; highs = [x[2] for x in data]
            lows = [x[3] for x in data]; closes = [x[4] for x in data]
            plt.figure(figsize=(8,4))
            for i in range(len(data)):
                color = 'green' if closes[i] >= opens[i] else 'red'
                plt.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1)
                plt.plot([times[i], times[i]], [opens[i], closes[i]], color=color, linewidth=4)
            plt.title("BTC 24h - velas 1h")
            plt.grid(alpha=0.3)
            plt.tight_layout()
            path = "/tmp/btc.png"
            plt.savefig(path)
            plt.close()
            print(">>> Grafico velas OK", flush=True)
            return path
    except Exception as e:
        print(f">>> Error chart velas: {e}", flush=True)

    # Intento 2: linea simple - este NUNCA falla
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=1"
        data = requests.get(url, timeout=15, headers=headers).json()
        prices = data['prices']
        times = [datetime.fromtimestamp(p[0]/1000, tz=TZ) for p in prices]
        vals = [p[1] for p in prices]
        plt.figure(figsize=(8,4))
        plt.plot(times, vals, linewidth=2)
        plt.title("BTC 24h")
        plt.grid(alpha=0.3)
        plt.tight_layout()
        path = "/tmp/btc.png"
        plt.savefig(path)
        plt.close()
        print(">>> Grafico linea OK", flush=True)
        return path
    except Exception as e:
        print(f">>> Error chart linea: {e}", flush=True)
    return None

def job_scheduled(with_chart=False):
    print(f">>> job_scheduled INICIADO chart={with_chart} {datetime.now(TZ)}", flush=True)
    price, change = get_price() # NUEVO: ahora recibe 2 valores
    if not price:
        print(">>> Fallo total obteniendo precio, envio mensaje de error", flush=True)
        send_text("⚠️ Bot BTC: no pude obtener el precio (API caida)")
        return
    sentiment=get_sentiment()
    # NUEVO: texto de variacion %
    sign = "📈" if change >=0 else "📉"
    change_txt = f"{sign} {change:+.2f}% 24h"

    msg = f"₿ *BTC: ${price:,.2f}* ({change_txt})\n{sentiment}\n📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España"
    send_text(msg)

    if with_chart: # NUEVO: a las 8 y 23 manda foto real
        chart_path = build_chart_image()
        if chart_path:
            send_photo(chart_path, f"📊 BTC ${price:,.2f} {change:+.2f}% 24h")

# NUEVO: para que conteste cuando le hablas
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"]["text"].lower()
            print(f">>> Mensaje recibido: {text}", flush=True)
            if "/start" in text or "hola" in text or "/help" in text:
                send_text("🤖 *Bot BTC*\n/precio - precio ahora\n/grafico - velas 24h", chat_id=chat_id)
            elif "precio" in text:
                p,c = get_price()
                send_text(f"₿ *BTC ahora: ${p:,.2f}*\n📈 {c:+.2f}% 24h", chat_id=chat_id)
            elif "grafico" in text or "gráfico" in text:
                p,c = get_price()
                path = build_chart_image()
                if path:
                    send_photo(path, f"₿ BTC ${p:,.2f} ({c:+.2f}%)", chat_id=chat_id)
                else:
                    send_text("No pude generar grafico", chat_id=chat_id)
            else:
                p,c = get_price()
                send_text(f"Escribe /precio o /grafico\nBTC ahora ${p:,.2f}", chat_id=chat_id)
    except Exception as e:
        print(f">>> Error webhook: {e}", flush=True)
    return "ok", 200

scheduler=BackgroundScheduler(timezone=TZ, daemon=True)
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=8, minute=0, id="btc8")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=13, minute=0, id="btc13")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=18, minute=0, id="btc18")
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=23, minute=0, id="btc23")
scheduler.start()
print(">>> Scheduler iniciado OK: 8,13,18,23 + webhook", flush=True)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
