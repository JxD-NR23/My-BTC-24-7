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
    headers = {"User-Agent": "Mozilla/5.0"}
    price = None
    change = 0.0

    # 1. Precio actual de Kraken
    try:
        j = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=15).json()
        price = float(j["result"]["XXBTZUSD"]["c"][0])
    except Exception as e:
        print(f">>> Error Kraken precio: {e}", flush=True)

    # 2. % 24h calculado desde el OHLC de Kraken (100% fiable)
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        # intervalo 1440 = 1 dia
        candles = list(j["result"]["XXBTZUSD"])
        if len(candles) >= 2:
            close_hoy = float(candles[-1][4])
            close_ayer = float(candles[-2][4])
            change = ((close_hoy - close_ayer) / close_ayer) * 100
            if price is None:
                price = close_hoy
            print(f">>> Kraken 24h OK: {price} {change:.2f}%", flush=True)
            return price, change
    except Exception as e:
        print(f">>> Error Kraken 24h: {e}", flush=True)

    # 3. Fallback Binance si Kraken falla
    try:
        j = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=15, headers=headers).json()
        print(f">>> Binance raw: {str(j)[:200]}", flush=True)
        change = float(j.get("priceChangePercent", 0))
        if price is None:
            price = float(j.get("lastPrice", 0))
        if price:
            return price, change
    except Exception as e:
        print(f">>> Error Binance: {e}", flush=True)

    return price, change

def get_sentiment():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()['data'][0]
        v=int(d['value']); emoji="😱" if v<25 else "😨" if v<45 else "😐" if v<55 else "🤑" if v<75 else "🤩"
        return f"{emoji} Fear & Greed {v}/100 ({d['value_classification']})"
    except: return "Sentimiento: --"

# NUEVO: genera imagen real de velas
def build_chart_image():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # Kraken OHLC 24h - 1 vela = 1 hora
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"
        data = requests.get(url, timeout=15, headers=headers).json()
        ohlc = list(data["result"]["XXBTZUSD"])
        # ultimas 24 velas
        ohlc = ohlc[-24:]

        times = [datetime.fromtimestamp(int(x[0]), tz=TZ) for x in ohlc]
        opens = [float(x[1]) for x in ohlc]
        highs = [float(x[2]) for x in ohlc]
        lows = [float(x[3]) for x in ohlc]
        closes = [float(x[4]) for x in ohlc]

        plt.figure(figsize=(8,4))
        for i in range(len(ohlc)):
            color = '#26a69a' if closes[i] >= opens[i] else '#ef5350'
            plt.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1)
            plt.plot([times[i], times[i]], [opens[i], closes[i]], color=color, linewidth=4)

        plt.title("BTC 24h - Kraken 1h", fontsize=12, fontweight='bold')
        plt.grid(alpha=0.3)
        plt.xticks(rotation=15)
        plt.tight_layout()
        path = "/tmp/btc.png"
        plt.savefig(path, dpi=150)
        plt.close()
        print(">>> Grafico Kraken OK", flush=True)
        return path
    except Exception as e:
        print(f">>> Error chart Kraken: {e}", flush=True)
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
