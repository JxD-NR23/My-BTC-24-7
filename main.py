# =================================================================================
# LO QUE HACE ESTE BOT ENTERO EXPLICADO EN HUMANO:
#
# 1. 8:00 y 23:00 -> Mensaje + Gráfico 24H en velas de 1H limpio (sin RSI ni medias)
# 2. 13:00 y 18:00 -> Solo mensaje, sin gráfico.
# 3. Cada 15 días a las 0:00 (día 1 y 15) -> Mensaje + Gráfico 30D en 1D con RSI, medias y patrones.
# 4. Todos los mensajes llevan: último aviso %, 24H %, 7D %, Rango 24H, RSI 1D, Sentimiento, Fecha España
# 5. Comandos: /grafico te da opción 1H o 1D
# PATCH v5.1: fix indent + MA incluye hoy + 60 velas para MA50 + volatility siempre guarda + workers 1
# =================================================================================

import os
import requests
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()
TZ = ZoneInfo("Europe/Madrid")
DATA_FILE = "/tmp/bot_data.json"
app = Flask(__name__)

KEYWORDS_ALTA_VOLATILIDAD = [
    "trump", "musk", "saylor", "warsh",
    "sec", "etf", "fed", "federal reserve", "reserva federal",
    "ban", "banea", "prohibe", "aprueba", "hack", "hackea", "crash", "guerra", "war"
]

# --- MEMORIA - Guarda el último precio para calcular % ---
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"last_price": 0, "last_aviso_price": 0, "alerts": [], "seen_news": []}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f">>> Error guardando data: {e}", flush=True)

# --- TELEGRAM - Envía mensaje de texto ---
def send_text(msg, chat_id=None):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id or CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=20)
        print(f">>> Telegram {r.status_code}", flush=True)
        return True
    except Exception as e:
        print(f">>> ERROR Telegram: {e}", flush=True)
        return False

# --- TELEGRAM - Envía foto con descripción ---
def send_photo(photo_path, caption="", chat_id=None):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as f:
            r = requests.post(url, data={"chat_id": chat_id or CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": f}, timeout=30)
        print(f">>> Foto {r.status_code}", flush=True)
    except Exception as e:
        print(f">>> Error foto: {e}", flush=True)

# --- PRECIO - Obtiene precio, % 24H, % 7D y cierres diarios ---
def get_price_full():
    price = None; change_24h = 0.0; change_7d = 0.0; closes = []
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])
        closes_daily = [float(c[4]) for c in candles]
        if len(candles) >= 2:
            change_24h = ((closes_daily[-1] - closes_daily[-2]) / closes_daily[-2]) * 100
        if len(candles) >= 8:
            change_7d = ((closes_daily[-1] - closes_daily[-8]) / closes_daily[-8]) * 100
        price = closes_daily[-1]
        print(f">>> Kraken Diario OK 24h:{change_24h:.2f}% 7d:{change_7d:.2f}%", flush=True)
    except Exception as e:
        print(f">>> Error Kraken diario: {e}", flush=True)

    if not price:
        try:
            j = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=10).json()
            price = float(j["result"]["XXBTZUSD"]["c"][0])
        except:
            pass
    if not price:
        try:
            j = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
            price = float(j.get("lastPrice",0))
            change_24h = float(j.get("priceChangePercent",0))
        except:
            pass
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])
        closes = [float(c[4]) for c in candles][-200:]
    except:
        closes = []
    return price, change_24h, change_7d, closes

def get_range_24h():
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])[-24:]
        lows = [float(c[3]) for c in candles]
        highs = [float(c[2]) for c in candles]
        return min(lows), max(highs), candles
    except:
        return 0, 0, []

def get_sentiment_week():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=7", timeout=10).json()['data']
        hoy = int(d[0]['value']); hace7 = int(d[6]['value']); diff = hoy - hace7
        emoji="😱" if hoy<25 else "😨" if hoy<45 else "😐" if hoy<55 else "🤑" if hoy<75 else "🤩"
        tendencia = "🔼 sube" if diff>5 else "🔽 baja" if diff<-5 else "➡ estable"
        return f"{emoji} *Fear & Greed {hoy}/100* ({d[0]['value_classification']})\n\nHace 7d: {hace7}/100 ({tendencia} {diff:+d})"
    except:
        return "Sentimiento: --"

def calc_rsi(prices, period=14):
    if len(prices) < period+1:
        return 50
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains = [d if d>0 else 0 for d in deltas[-period:]]
    losses = [-d if d<0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    if avg_loss == 0:
        return 100
    rs = avg_gain/avg_loss
    rsi = 100 - (100/(1+rs))
    return rsi

def detect_pattern_24h_simple(candles_24h):
    patrones = []
    try:
        closes = [float(c[4]) for c in candles_24h]
        highs = [float(c[2]) for c in candles_24h]
        lows = [float(c[3]) for c in candles_24h]
        if len(closes) >= 24:
            max_prev = max(highs[:-1])
            min_prev = min(lows[:-1])
            if closes[-1] > max_prev:
                patrones.append(f"🚀 Rompiendo máximo 24H (${max_prev:,.0f})")
            if closes[-1] < min_prev:
                patrones.append(f"💥 Perdiendo mínimo 24H (${min_prev:,.0f})")
        if not patrones:
            patrones.append("➡ Sin patrón relevante en 24H - Rango lateral")
    except:
        patrones.append("Patrón: --")
    return patrones

def detect_pattern_30d_pro(closes, highs, lows, rsi):
    patrones = []
    if rsi > 70:
        patrones.append(f"🔥 RSI 1D {rsi:.0f} Sobrecomprado")
    elif rsi < 30:
        patrones.append(f"🧊 RSI 1D {rsi:.0f} Sobreventa")
    if len(closes) >= 50:
        ma20 = sum(closes[-20:])/20
        ma50 = sum(closes[-50:])/50
        if ma20 > ma50:
            patrones.append(f"📈 Tendencia alcista (MA20 ${ma20:,.0f} > MA50 ${ma50:,.0f})")
        else:
            patrones.append(f"📉 Tendencia bajista (MA20 ${ma20:,.0f} < MA50 ${ma50:,.0f})")
        ma20_prev = sum(closes[-21:-1])/20
        ma50_prev = sum(closes[-51:-1])/50
        if ma20_prev <= ma50_prev and ma20 > ma50:
            patrones.append("✨ Cruce dorado - MA20 cruza por encima MA50")
        if ma20_prev >= ma50_prev and ma20 < ma50:
            patrones.append("⚠ Cruce de muerte - MA20 cruza por debajo MA50")
    if len(closes) >= 30:
        max_30 = max(highs[:-1])
        min_30 = min(lows[:-1])
        if closes[-1] > max_30:
            patrones.append(f"🚀 Breakout 30D - Nuevo máximo ${max_30:,.0f}")
        if closes[-1] < min_30:
            patrones.append(f"💥 Breakdown 30D - Nuevo mínimo ${min_30:,.0f}")
    if not patrones:
        patrones.append("➡ Sin patrón relevante 30D")
    return patrones

def build_chart_24h_1h_clean():
    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"
        data = requests.get(url, timeout=15).json()
        ohlc = list(data["result"]["XXBTZUSD"])[-24:]
        times = [datetime.fromtimestamp(int(x[0]), tz=TZ) for x in ohlc]
        closes = [float(x[4]) for x in ohlc]
        highs = [float(x[2]) for x in ohlc]
        lows = [float(x[3]) for x in ohlc]
        opens = [float(x[1]) for x in ohlc]

        fig, ax1 = plt.subplots(1, 1, figsize=(12,5))

        for i in range(len(ohlc)):
            color = '#26a69a' if closes[i] >= opens[i] else '#ef5350'
            ax1.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1)
            ax1.plot([times[i], times[i]], [opens[i], closes[i]], color=color, linewidth=6)

        min_p = min(lows); max_p = max(highs)
        ax1.set_title(f"BTC 24H (1H) | Rango ${min_p:,.0f} - ${max_p:,.0f}", fontsize=12, fontweight='bold')
        ax1.grid(alpha=0.3)
        plt.xticks(rotation=20); plt.tight_layout()
        path = "/tmp/btc_24h_1h.png"
        plt.savefig(path, dpi=150); plt.close()
        print(">>> Gráfico 24H 1H limpio OK", flush=True)

        patrones = detect_pattern_24h_simple(ohlc)
        return path, min_p, max_p, patrones, ohlc
    except Exception as e:
        print(f">>> Error chart 24H 1H: {e}", flush=True)
        return None, 0, 0, [], []

# --- BLOQUE CORREGIDO v5.1 - FIX MA + 60 VELAS ---
def build_chart_30d_1d_pro():
    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440"
        data = requests.get(url, timeout=15).json()
        ohlc_all = list(data["result"]["XXBTZUSD"])[-60:]  # FIX: 60 para poder calcular MA50
        if len(ohlc_all) < 30:
            raise ValueError("No hay suficientes velas")
        
        # Datos completos para calculos
        closes_all = [float(x[4]) for x in ohlc_all]
        highs_all = [float(x[2]) for x in ohlc_all]
        lows_all = [float(x[3]) for x in ohlc_all]
        
        # Solo ultimos 30 para visualizacion
        ohlc = ohlc_all[-30:]
        times = [datetime.fromtimestamp(int(x[0]), tz=TZ) for x in ohlc]
        closes = [float(x[4]) for x in ohlc]
        highs = [float(x[2]) for x in ohlc]
        lows = [float(x[3]) for x in ohlc]
        opens = [float(x[1]) for x in ohlc]

        # FIX: MA ahora incluye el dia de hoy (i-19:i+1)
        ma20_all = [sum(closes_all[i-19:i+1])/20 if i>=19 else None for i in range(len(closes_all))]
        ma50_all = [sum(closes_all[i-49:i+1])/50 if i>=49 else None for i in range(len(closes_all))]
        ma20 = ma20_all[-30:]
        ma50 = ma50_all[-30:]

        rsi = calc_rsi(closes_all)  # RSI sobre historico completo

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10,6), gridspec_kw={'height_ratios':[3,1]})

        for i in range(len(ohlc)):
            color = '#26a69a' if closes[i] >= opens[i] else '#ef5350'
            ax1.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1)
            ax1.plot([times[i], times[i]], [opens[i], closes[i]], color=color, linewidth=5)

        ax1.plot(times, ma20, color='#FFC107', linewidth=1.5, label='MA20')
        if any(m is not None for m in ma50):
            ax1.plot(times, ma50, color='#FF5722', linewidth=1.2, label='MA50')

        min_p = min(lows); max_p = max(highs)
        ax1.set_title(f"BTC 30D (1D) | Rango ${min_p:,.0f} - ${max_p:,.0f} | RSI {rsi:.1f}", fontsize=11, fontweight='bold')
        ax1.legend(); ax1.grid(alpha=0.3)

        # --- COLOR DINÁMICO RSI ---
        rsi_hist = [calc_rsi(closes_all[:i+1]) for i in range(len(closes_all))][-30:]
        if rsi > 70:
            rsi_color = "red"
            estado = "SOBRECOMPRA 🔥"
        elif rsi >= 68:
            rsi_color = "orange"
            estado = "CASI SOBRECOMPRA ⚠"
        elif rsi < 30:
            rsi_color = "#0088ff"
            estado = "SOBREVENTA 🧊"
        else:
            rsi_color = "purple"
            estado = "NEUTRAL"

        ax2.plot(times, rsi_hist, color=rsi_color, linewidth=2)
        ax2.axhline(70, color='red', linestyle='--', alpha=0.5)
        ax2.axhline(30, color='green', linestyle='--', alpha=0.5)
        ax2.axhspan(68, 70, color='orange', alpha=0.15)
        ax2.axhspan(70, 100, color='red', alpha=0.15)
        ax2.axhspan(0, 30, color='blue', alpha=0.15)
        ax2.set_ylim(0,100)
        ax2.set_ylabel('RSI')
        ax2.grid(alpha=0.3)
        ax2.set_title(f"RSI 1D: {estado} ({rsi:.1f})", color=rsi_color, fontweight='bold', fontsize=9)

        plt.xticks(rotation=15); plt.tight_layout()
        path = "/tmp/btc_30d_1d.png"
        plt.savefig(path, dpi=150); plt.close()
        print(">>> Gráfico 30D 1D PRO OK v5.1", flush=True)

        patrones = detect_pattern_30d_pro(closes_all, highs_all, lows_all, rsi)
        ma20_last = ma20[-1] if ma20[-1] is not None else 0
        return path, rsi, min_p, max_p, ma20_last, patrones
    except Exception as e:
        print(f">>> Error chart 30D 1D: {e}", flush=True)
        return None, 50, 0, 0, 0, []

def get_filtered_news():
    try:
        url = "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&currencies=BTC&filter=hot"
        try:
            data = requests.get(url, timeout=10).json()
            news = data.get('results',[])[:10]
        except:
            return []
        data_mem = load_data(); seen = data_mem.get("seen_news",[]); alertas = []
        for n in news:
            title = (n.get('title','') or '').lower()
            news_id = n.get('id')
            if news_id in seen:
                continue
            if any(k in title for k in KEYWORDS_ALTA_VOLATILIDAD):
                alertas.append(n); seen.append(news_id)
                if len(seen)>100:
                    seen = seen[-100:]
        data_mem["seen_news"]=seen; save_data(data_mem)
        return alertas
    except Exception as e:
        print(f">>> Error news: {e}", flush=True)
        return []

def job_daily(with_chart=False, chart_type="24h"):
    print(f">>> job_daily INICIADO chart={with_chart} type={chart_type} {datetime.now(TZ)}", flush=True)
    price, change24, change7, closes_diario = get_price_full()
    if not price:
        send_text("⚠ Bot BTC: API caída")
        return
    data = load_data()
    last_aviso = data.get("last_aviso_price", price)
    change_aviso = ((price-last_aviso)/last_aviso*100) if last_aviso else 0
    def fmt(c):
        return f"{'📈' if c>=0 else '📉'} {c:+.2f}%"
    rsi_1d = calc_rsi(closes_diario)
    if rsi_1d >= 70:
        rsi_1d_estado = "🔥 Sobrecomprado"
    elif rsi_1d >= 68:
        rsi_1d_estado = "⚠ Casi Sobrecompra"
    elif rsi_1d <= 30:
        rsi_1d_estado = "🧊 Sobreventa"
    elif rsi_1d <= 32:
        rsi_1d_estado = "⚠ Casi Sobreventa"
    elif rsi_1d > 55:
        rsi_1d_estado = "⚖ Neutral Alcista"
    elif rsi_1d < 45:
        rsi_1d_estado = "⚖ Neutral Bajista"
    else:
        rsi_1d_estado = "⚖ Neutral"
    rsi_1d_txt = f"{rsi_1d:.0f} {rsi_1d_estado}"
    min_24h, max_24h, candles_24h = get_range_24h()
    rango_24h_txt = f"📊 Rango 24H: ${min_24h:,.0f} - ${max_24h:,.0f}" if min_24h else "📊 Rango 24H: --"
    sentiment = get_sentiment_week()
    price_big = f"💰 *₿ BTC ${price:,.2f}* 💰"
    msg = (
        f"{price_big}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🔄 Último aviso: {fmt(change_aviso)}\n\n"
        f"🕐 24h: {fmt(change24)}\n\n"
        f"📅 7d: {fmt(change7)}\n\n"
        f"{rango_24h_txt}\n\n"
        f"📈 RSI 1D: {rsi_1d_txt}\n\n"
        f"{sentiment}\n\n"
        f"📅 {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')} España\n"
    )
    chart_path = None
    patrones = []
    if with_chart and chart_type == "24h":
        path, min_c, max_c, pat, _ = build_chart_24h_1h_clean()
        chart_path = path
        patrones = pat
        if patrones:
            msg += f"\n🔍 *Patrón 24H:*\n\n" + "\n\n".join([f"• {p}" for p in patrones]) + "\n"
    send_text(msg)
    if with_chart and chart_path:
        send_photo(chart_path, f"📊 BTC 24H (1H) ${price:,.2f} | {rango_24h_txt}")
    data["last_aviso_price"] = price
    data["last_price"] = price
    save_data(data)
    check_custom_alerts(price)

def job_15dias():
    print(f">>> job_15dias INICIADO {datetime.now(TZ)}", flush=True)
    price, change24, change7, closes_diario = get_price_full()
    if not price:
        send_text("⚠ Bot BTC: API caída reporte 15 días")
        return
    data = load_data()
    last_aviso = data.get("last_aviso_price", price)
    change_aviso = ((price-last_aviso)/last_aviso*100) if last_aviso else 0
    def fmt(c):
        return f"{'📈' if c>=0 else '📉'} {c:+.2f}%"
    path, rsi_30d, min_30d, max_30d, ma20, patrones_30d = build_chart_30d_1d_pro()
    # --- CLASIFICACIÓN RSI CORREGIDA - 5 ESTADOS - FIX INDENT ---
    if rsi_1d >= 70:
        rsi_1d_estado = "🔥 Sobrecomprado"
    elif rsi_1d >= 68:
        rsi_1d_estado = "⚠ Casi Sobrecompra"
    elif rsi_1d <= 30:
        rsi_1d_estado = "🧊 Sobreventa"
    elif rsi_1d <= 32:
        rsi_1d_estado = "⚠ Casi Sobreventa"
    elif rsi_1d > 55:
        rsi_1d_estado = "⚖ Neutral Alcista"
    elif rsi_1d < 45:
        rsi_1d_estado = "⚖ Neutral Bajista"
    else:
        rsi_1d_estado = "⚖ Neutral"

    rsi_txt = f"{rsi_30d:.0f} {rsi_estado}"
    rango_24h_min, rango_24h_max, _ = get_range_24h()
    rango_24h_txt = f"📊 Rango 24H: ${rango_24h_min:,.0f} - ${rango_24h_max:,.0f}" if rango_24h_min else "📊 Rango 24H: --"
    rango_30d_txt = f"📊 Rango 30D: ${min_30d:,.0f} - ${max_30d:,.0f}" if min_30d else "📊 Rango 30D: --"
    sentiment = get_sentiment_week()
    price_big = f"💰 *₿ BTC ${price:,.2f}* 💰"
    msg = (
        f"📅 *REPORTE CADA 15 DÍAS - 30D*\n\n"
        f"{price_big}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🔄 Último aviso: {fmt(change_aviso)}\n\n"
        f"🕐 24h: {fmt(change24)}\n\n"
        f"📅 7d: {fmt(change7)}\n\n"
        f"{rango_24h_txt}\n\n"
        f"{rango_30d_txt}\n\n"
        f"📈 RSI 1D: {rsi_txt}\n\n"
        f"🔍 *Análisis 30D:*\n\n" + "\n\n".join([f"• {p}" for p in patrones_30d]) + "\n\n"
        f"{sentiment}\n\n"
        f"📅 {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')} España\n"
    )
    send_text(msg)
    if path:
        send_photo(path, f"📊 BTC 30D (1D) ${price:,.2f} | RSI {rsi_30d:.0f} | {rango_30d_txt}")
    data["last_aviso_price"] = price
    data["last_price"] = price
    save_data(data)
    check_custom_alerts(price)

def check_volatility():
    data = load_data(); last = data.get("last_price",0)
    price, c24, _, _ = get_price_full()
    if not price:
        return
    if not last:
        data["last_price"]=price; save_data(data); return
    change = ((price-last)/last*100)
    if abs(change) >= 5:
        signo = "🚀 SUBIDÓN" if change>0 else "💥 CRASH"
        send_text(f"⚠ *ALERTA VOLATILIDAD {signo}*\n\n₿ BTC ${price:,.2f} ({change:+.2f}% en 5 min)")
    # FIX v5.1: siempre guarda el precio para no quedarse desactualizado
    data["last_price"]=price; save_data(data)

def check_custom_alerts(current_price):
    data = load_data(); alerts = data.get("alerts",[]); restantes = []
    for a in alerts:
        try:
            tipo = a["type"]; valor = a["value"]; chat = a.get("chat_id", CHAT_ID)
            if (tipo==">" and current_price>=valor) or (tipo=="<" and current_price<=valor):
                send_text(f"🔔 *ALERTA PERSONALIZADA*\n\nBTC ha cruzado {'por arriba' if tipo=='>' else 'por abajo'} de ${valor:,.2f}\n\nAhora: ${current_price:,.2f}", chat_id=chat)
            else:
                restantes.append(a)
        except:
            pass
    data["alerts"]=restantes; save_data(data)

def check_news_job():
    news = get_filtered_news()
    for n in news[:1]:
        title = n.get('title',''); url = n.get('url','')
        send_text(f"🗞 *NOTICIA DE ALTO IMPACTO BTC*\n\n{title}\n\n{url}")

@app.route('/')
def home():
    return f"Bot running v5.1! Token:{bool(TOKEN)} Chat:{bool(CHAT_ID)}"

@app.route('/test')
def test():
    job_daily(True, "24h")
    return "Test 24H 1H enviado!"

@app.route('/test30d')
def test30d():
    job_15dias()
    return "Test 30D 1D enviado!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if "message" not in data or "text" not in data["message"]:
            return "ok",200
        chat_id = data["message"]["chat"]["id"]
        text_raw = data["message"]["text"]
        text = text_raw.lower()

        if "/start" in text or "/help" in text:
            send_text(
                "🤖 *Ferrari Bot v5.1 FINAL*\n\n"
                "*Avisos automáticos:*\n\n"
                "8:00 y 23:00 -> Mensaje + Gráfico 24H (1H limpio) + patrón\n\n"
                "13:00 y 18:00 -> Solo mensaje\n\n"
                "Día 1 y 15 a las 0:00 -> Mensaje + Gráfico 30D (1D) con RSI, medias y patrón\n\n"
                "*Comandos:*\n\n"
                "/precio\n\n"
                "/grafico -> elige 1H o 1D\n\n"
                "/grafico1h -> 24H limpio\n\n"
                "/grafico1d -> 30D pro\n\n"
                "/alerta >90000\n\n"
                "/misalertas\n\n"
                "/sentimiento\n\n"
                "/noticias", chat_id=chat_id)

        elif "/precio" in text:
            p,c24, c7, closes = get_price_full()
            d = load_data(); last_aviso = d.get("last_aviso_price", p)
            ch_aviso = ((p-last_aviso)/last_aviso*100) if last_aviso else 0
            rsi = calc_rsi(closes)
            min24, max24, _ = get_range_24h()
            send_text(f"💰 *BTC ${p:,.2f}*\n\n🔄 Último aviso: {ch_aviso:+.2f}%\n\n🕐 24h: {c24:+.2f}%\n\n📅 7d: {c7:+.2f}%\n\n📊 Rango 24H: ${min24:,.0f} - ${max24:,.0f}\n\n📈 RSI 1D: {rsi:.0f}", chat_id=chat_id)

        elif text.strip() == "/grafico":
            send_text(
                "📊 *¿Qué gráfico quieres?*\n\n"
                "/grafico1h -> 24H en velas 1H limpio\n\n"
                "/grafico1d -> 30D en velas 1D con rango, RSI, cruce medias y patrón\n\n"
                "Auto: 8 y 23h -> 1H limpio, día 1 y 15 0:00 -> 30D pro",
                chat_id=chat_id)

        elif "grafico1h" in text:
            p,_,_,_ = get_price_full()
            path, min_p, max_p, patrones, _ = build_chart_24h_1h_clean()
            if path:
                txt_pat = "\n\n".join(patrones)
                send_photo(path, f"BTC 24H (1H) ${p:,.2f}\n\nRango ${min_p:,.0f}-${max_p:,.0f}\n\n{txt_pat}", chat_id=chat_id)
            else:
                send_text("Error gráfico 1H", chat_id=chat_id)

        elif "grafico1d" in text or "grafico30d" in text:
            p,_,_,_ = get_price_full()
            path, rsi, min_p, max_p, ma20, patrones = build_chart_30d_1d_pro()
            if path:
                txt_pat = "\n\n".join(patrones)
                send_photo(path, f"BTC 30D (1D) ${p:,.2f} RSI {rsi:.0f}\n\nRango ${min_p:,.0f}-${max_p:,.0f}\n\n{txt_pat}", chat_id=chat_id)
            else:
                send_text("Error gráfico 30D", chat_id=chat_id)

        elif "grafico" in text:
            send_text("Escribe /grafico para elegir 1H o 1D", chat_id=chat_id)

        elif "/alerta" in text:
            m = re.search(r'([<>])\s*(\d+)', text_raw)
            if m:
                tipo=m.group(1); valor=float(m.group(2))
                d=load_data(); d["alerts"].append({"type":tipo,"value":valor,"chat_id":chat_id}); save_data(d)
                send_text(f"✅ Alerta creada: te aviso cuando BTC {tipo} ${valor:,.0f}", chat_id=chat_id)
            else:
                send_text("Usa: /alerta >95000 o /alerta <80000", chat_id=chat_id)

        elif "misalertas" in text:
            d=load_data(); al = [a for a in d.get("alerts",[]) if a.get("chat_id")==chat_id]
            if not al:
                send_text("No tienes alertas", chat_id=chat_id)
            else:
                txt = "\n\n".join([f"{a['type']} ${a['value']}" for a in al])
                send_text(f"🔔 Tus alertas:\n\n{txt}\n\nBorra con /borraralertas", chat_id=chat_id)

        elif "borraralertas" in text:
            d=load_data(); d["alerts"]=[a for a in d["alerts"] if a.get("chat_id")!=chat_id]; save_data(d)
            send_text("🗑 Alertas borradas", chat_id=chat_id)

        elif "sentimiento" in text:
            send_text(get_sentiment_week(), chat_id=chat_id)

        elif "noticias" in text:
            n = get_filtered_news()
            if not n:
                send_text("No hay noticias de alto impacto ahora", chat_id=chat_id)
            else:
                send_text(f"🗞 {n[0]['title']}\n\n{n[0]['url']}", chat_id=chat_id)

        else:
            p,c24,_,_ = get_price_full()
            send_text(f"Escribe /grafico para elegir 1H o 1D\n\nBTC ${p:,.2f}", chat_id=chat_id)

    except Exception as e:
        print(f">>> Error webhook: {e}", flush=True)
    return "ok",200

scheduler=BackgroundScheduler(timezone=TZ, daemon=True)
scheduler.add_job(lambda: job_daily(True, "24h"), 'cron', hour=8, minute=0, id="btc8")
scheduler.add_job(lambda: job_daily(False, "24h"), 'cron', hour=13, minute=0, id="btc13")
scheduler.add_job(lambda: job_daily(False, "24h"), 'cron', hour=18, minute=0, id="btc18")
scheduler.add_job(lambda: job_daily(True, "24h"), 'cron', hour=23, minute=0, id="btc23")
scheduler.add_job(job_15dias, 'cron', day='1,15', hour=0, minute=0, id="cada15dias")
scheduler.add_job(check_volatility, 'interval', minutes=5, id="vol")
scheduler.add_job(check_news_job, 'interval', minutes=10, id="news")
scheduler.start()
print(">>> Scheduler v5.1 FINAL: 8(24H),13,18,23(24H) + cada 15 días 0:00 30D + vol 5m + news 10m FIX MA+indent", flush=True)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
