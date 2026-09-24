# =================================================================================
# LO QUE HACE ESTE BOT ENTERO EXPLICADO EN HUMANO:
#
# 1. 8:00 y 23:00 -> Mensaje + Grafico 24H en velas de 1H limpio (sin RSI ni medias)
# Si ve patron importante (breakout, breakdown) te lo dice en el mensaje.
#
# 2. 13:00 y 18:00 -> Solo mensaje, sin grafico.
#
# 3. Cada 15 dias a las 0:00 (dia 1 y 15 de cada mes) -> Mensaje + Grafico 30D en 1D
# con rango, RSI, cruce de medias y patrones.
#
# 4. Todos los mensajes diarios llevan SIEMPRE (como pediste):
# - Ultimo aviso % (cambio desde el aviso anterior)
# - 24H % y 7D % (cambio vs ayer y hace 7 dias)
# - Rango de precios 24H (min y max de las ultimas 24 horas)
# - RSI 1D en el momento exacto
# - Sentimiento actual y comparado hace 7 dias (Fear & Greed)
# - Fecha actual de España
# - Texto super separado con lineas en blanco
#
# 5. Comandos: /grafico te da opcion 1H o 1D
# =================================================================================

# ---------------------------------------------------------------------------------
# BLOQUE 1: IMPORTS - HERRAMIENTAS QUE LE DAMOS AL BOT
# ---------------------------------------------------------------------------------
# os = Operating System. Para leer secretos de Render. os.environ.get lee variable de entorno.
# requests = Para hablar con internet. get pide datos, post manda datos.
# json = Formato para guardar datos. Guarda diccionarios como texto.
# re = Regular Expressions. Para entender si escribes ">90000"
# datetime = Para fechas. datetime.now() = ahora.
# timedelta = Para restar dias. No lo usamos mucho pero es util.
# ZoneInfo = Para que la hora sea España y no UTC.
# Flask = Mini servidor web. Render exige una web para que diga Live.
# request = Lo que nos manda Telegram cuando escribes.
# BackgroundScheduler = Despertador que ejecuta funciones a una hora sin parar.
# matplotlib = Para dibujar graficos.
# matplotlib.use('Agg') = Dibuja sin pantalla, obligatorio en Render que no tiene monitor.
# pyplot as plt = El lapiz que dibuja.
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

# ---------------------------------------------------------------------------------
# BLOQUE 2: CONFIGURACION - TUS LLAVES
# ---------------------------------------------------------------------------------
# TOKEN = Contraseña de tu bot de Telegram que te da @BotFather..strip() quita espacios si copiaste mal.
# CHAT_ID = Tu ID de chat. A quien avisa por defecto.
# TZ = Zona horaria. Europe/Madrid = UTC+1 en invierno, UTC+2 en verano.
# DATA_FILE = Archivo donde guarda memoria. /tmp es gratis en Render pero se borra si reinicia.
# app = Flask(__name__) = Creamos la app web. __name__ vale "__main__" cuando ejecutas este archivo.
# KEYWORDS = Palabras que si mueven BTC 3% en minutos. Si no filtramos, spam de 100 noticias al dia.
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()
TZ = ZoneInfo("Europe/Madrid")
DATA_FILE = "/tmp/bot_data.json"
app = Flask(__name__)

KEYWORDS_ALTA_VOLATILIDAD = [
    "trump", "musk", "saylor", "warsh", # Personas que con un tuit mueven mercado
    "sec", "etf", "fed", "federal reserve", "reserva federal", # Regulacion USA
    "ban", "banea", "prohibe", "aprueba", "hack", "hackea", "crash", "guerra", "war" # Panico
]

# ---------------------------------------------------------------------------------
# BLOQUE 3: MEMORIA - COMO RECUERDA
# ---------------------------------------------------------------------------------
def load_data():
    """Abre cuaderno. Si no existe, crea uno vacio con valores por defecto."""
    try: # try = intenta hacer esto
        with open(DATA_FILE, 'r') as f: # 'r' = read = leer
            return json.load(f) # json.load = texto -> dict Python
    except: # Si falla (no existe archivo primera vez)
        return {"last_price": 0, "last_aviso_price": 0, "alerts": [], "seen_news": []}

def save_data(data):
    """Guarda cuaderno. 'w' = write = escribir. json.dump = dict -> texto"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f">>> Error guardando data: {e}", flush=True) # flush=True = sale al instante en Logs Render

# ---------------------------------------------------------------------------------
# BLOQUE 4: TELEGRAM - COMO HABLA
# ---------------------------------------------------------------------------------
def send_text(msg, chat_id=None):
    """Manda texto. POST a api.telegram.org/botTOKEN/sendMessage con chat_id y text."""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id or CHAT_ID, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=20)
        print(f">>> Telegram {r.status_code}", flush=True) # 200 = OK
        return True
    except Exception as e:
        print(f">>> ERROR Telegram: {e}", flush=True)
        return False

def send_photo(photo_path, caption="", chat_id=None):
    """Manda foto. Abre foto en 'rb' = read binary y la manda con files=."""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as f:
            r = requests.post(url, data={"chat_id": chat_id or CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": f}, timeout=30)
        print(f">>> Foto {r.status_code}", flush=True)
    except Exception as e: print(f">>> Error foto: {e}", flush=True)

# ---------------------------------------------------------------------------------
# BLOQUE 5: PRECIO - CORAZON
# ---------------------------------------------------------------------------------
def get_price_full():
    """
    Devuelve 4 cosas:
    price = precio actual
    change_24h = % vs ayer
    change_7d = % vs hace 7 dias
    closes = lista 200 cierres diarios para RSI
    Como: Kraken OHLC interval 1440 = velas de 1 dia. c[4] = close.
    Formula % = ((ahora - antes) / antes) * 100
    """
    price = None; change_24h = 0.0; change_7d = 0.0; closes = []
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])
        closes_daily = [float(c[4]) for c in candles] # List comprehension: por cada vela, coge cierre y conviertelo a numero
        if len(candles) >= 2:
            change_24h = ((closes_daily[-1] - closes_daily[-2]) / closes_daily[-2]) * 100
        if len(candles) >= 8:
            change_7d = ((closes_daily[-1] - closes_daily[-8]) / closes_daily[-8]) * 100
        price = closes_daily[-1]
        print(f">>> Kraken Diario OK 24h:{change_24h:.2f}% 7d:{change_7d:.2f}%", flush=True)
    except Exception as e: print(f">>> Error Kraken diario: {e}", flush=True)

    if not price: # Plan B si Kraken diario falla
        try:
            j = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=10).json()
            price = float(j["result"]["XXBTZUSD"]["c"][0])
        except: pass
    if not price: # Plan C Binance
        try:
            j = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
            price = float(j.get("lastPrice",0))
            change_24h = float(j.get("priceChangePercent",0))
        except: pass
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])
        closes = [float(c[4]) for c in candles][-200:] # Ultimas 200
    except: closes = []
    return price, change_24h, change_7d, closes

# ---------------------------------------------------------------------------------
# BLOQUE 6: RANGO 24H - NUEVO PARA CUMPLIR LO QUE PEDISTE
# ---------------------------------------------------------------------------------
def get_range_24h():
    """
    QUE HACE: Trae ultimas 24 velas de 1H y calcula min y max.
    PARA QUE: Para tu mensaje diario "Rango 24H: $xx - $yy"
    COMO: Kraken interval 60 = 1 hora. [-24:] = ultimas 24
    """
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])[-24:] # 24 horas
        lows = [float(c[3]) for c in candles] # c[3] = low = minimo de esa hora
        highs = [float(c[2]) for c in candles] # c[2] = high = maximo
        return min(lows), max(highs), candles # Devuelve min, max y velas para patron
    except:
        return 0, 0, []

# ---------------------------------------------------------------------------------
# BLOQUE 7: SENTIMIENTO - ACTUAL VS HACE 7D
# ---------------------------------------------------------------------------------
def get_sentiment_week():
    """Fear & Greed 0-100. 0 panico, 100 avaricia. Compara hoy vs hace 7 dias."""
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=7", timeout=10).json()['data']
        hoy = int(d[0]['value']); hace7 = int(d[6]['value']); diff = hoy - hace7
        emoji="😱" if hoy<25 else "😨" if hoy<45 else "😐" if hoy<55 else "🤑" if hoy<75 else "🤩"
        tendencia = "🔼 sube" if diff>5 else "🔽 baja" if diff<-5 else "➡️ estable"
        # \n\n = Doble salto para texto mas separado como pediste
        return f"{emoji} *Fear & Greed {hoy}/100* ({d[0]['value_classification']})\n\nHace 7d: {hace7}/100 ({tendencia} {diff:+d})"
    except: return "Sentimiento: --"

# ---------------------------------------------------------------------------------
# BLOQUE 8: RSI
# ---------------------------------------------------------------------------------
def calc_rsi(prices, period=14):
    """RSI >70 sobrecomprado, <30 sobreventa. Formula oficial."""
    if len(prices) < period+1: return 50
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains = [d if d>0 else 0 for d in deltas[-period:]]
    losses = [-d if d<0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    if avg_loss == 0: return 100
    rs = avg_gain/avg_loss
    rsi = 100 - (100/(1+rs))
    return rsi

# ---------------------------------------------------------------------------------
# BLOQUE 9: DETECTOR DE PATRONES - SIMPLE SIN RSI NI MEDIAS PARA 1H
# ---------------------------------------------------------------------------------
def detect_pattern_24h_simple(candles_24h):
    """
    PARA GRAFICO 1H 24H LIMPIO QUE PEDISTE (sin RSI ni medias).
    Solo detecta si esta rompiendo max/min de 24H.
    candles_24h = lista de 24 velas de 1H
    """
    patrones = []
    try:
        closes = [float(c[4]) for c in candles_24h]
        highs = [float(c[2]) for c in candles_24h]
        lows = [float(c[3]) for c in candles_24h]
        if len(closes) >= 24:
            max_prev = max(highs[:-1]) # Maximo sin contar la ultima vela
            min_prev = min(lows[:-1])
            if closes[-1] > max_prev:
                patrones.append(f"🚀 Rompiendo maximo 24H (${max_prev:,.0f}) - Posible patron alcista")
            if closes[-1] < min_prev:
                patrones.append(f"💥 Perdiendo minimo 24H (${min_prev:,.0f}) - Posible patron bajista")
        if not patrones:
            patrones.append("➡️ Sin patron relevante en 24H - Rango lateral")
    except:
        patrones.append("Patron: --")
    return patrones

def detect_pattern_30d_pro(closes, highs, lows, rsi):
    """
    PARA GRAFICO 30D 1D PRO que pediste cada 15 dias.
    Aqui SI usamos RSI, cruce medias y patrones porque lo pediste completo.
    """
    patrones = []
    # RSI
    if rsi > 70: patrones.append(f"🔥 RSI 1D {rsi:.0f} Sobrecomprado")
    elif rsi < 30: patrones.append(f"🧊 RSI 1D {rsi:.0f} Sobreventa")
    # Cruce medias MA20 y MA50
    if len(closes) >= 50:
        ma20 = sum(closes[-20:])/20
        ma50 = sum(closes[-50:])/50
        if ma20 > ma50: patrones.append(f"📈 Tendencia alcista (MA20 ${ma20:,.0f} > MA50 ${ma50:,.0f})")
        else: patrones.append(f"📉 Tendencia bajista (MA20 ${ma20:,.0f} < MA50 ${ma50:,.0f})")
        # Cruce
        ma20_prev = sum(closes[-21:-1])/20
        ma50_prev = sum(closes[-51:-1])/50
        if ma20_prev <= ma50_prev and ma20 > ma50:
            patrones.append("✨ Cruce dorado - MA20 cruza por encima MA50")
        if ma20_prev >= ma50_prev and ma20 < ma50:
            patrones.append("⚠️ Cruce de muerte - MA20 cruza por debajo MA50")
    # Breakout 30D
    if len(closes) >= 30:
        max_30 = max(highs[:-1])
        min_30 = min(lows[:-1])
        if closes[-1] > max_30: patrones.append(f"🚀 Breakout 30D - Nuevo maximo ${max_30:,.0f}")
        if closes[-1] < min_30: patrones.append(f"💥 Breakdown 30D - Nuevo minimo ${min_30:,.0f}")
    if not patrones:
        patrones.append("➡️ Sin patron relevante 30D")
    return patrones

# ---------------------------------------------------------------------------------
# BLOQUE 10: GRAFICO 24H - 1H - LIMPIO SIN RSI NI MEDIAS - PARA 8:00 Y 23:00
# ---------------------------------------------------------------------------------
def build_chart_24h_1h_clean():
    """
    QUE HACE: Grafico de ultimas 24 horas en velas de 1 hora, LIMPIO como pediste.
    SIN RSI, SIN MEDIAS, solo velas verdes/rojas.
    COMO LO DIBUJA:
    - plt.subplots(1,1) = solo 1 grafico, no 2 como antes
    - Por cada vela dibuja mecha (low-high) y cuerpo (open-close)
    - Verde #26a69a si sube, rojo #ef5350 si baja
    """
    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60" # 60 = 1 hora
        data = requests.get(url, timeout=15).json()
        ohlc = list(data["result"]["XXBTZUSD"])[-24:] # Solo 24 velas = 24 horas
        times = [datetime.fromtimestamp(int(x[0]), tz=TZ) for x in ohlc]
        closes = [float(x[4]) for x in ohlc]
        highs = [float(x[2]) for x in ohlc]
        lows = [float(x[3]) for x in ohlc]
        opens = [float(x[1]) for x in ohlc]

        fig, ax1 = plt.subplots(1, 1, figsize=(12,5)) # Solo 1 grafico

        for i in range(len(ohlc)):
            color = '#26a69a' if closes[i] >= opens[i] else '#ef5350'
            ax1.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1) # Mecha
            ax1.plot([times[i], times[i]], [opens[i], closes[i]], color=color, linewidth=6) # Cuerpo mas grueso

        min_p = min(lows); max_p = max(highs)
        ax1.set_title(f"BTC 24H (1H) | Rango ${min_p:,.0f} - ${max_p:,.0f}", fontsize=12, fontweight='bold')
        ax1.grid(alpha=0.3)
        plt.xticks(rotation=20); plt.tight_layout()
        path = "/tmp/btc_24h_1h.png"
        plt.savefig(path, dpi=150); plt.close()
        print(">>> Grafico 24H 1H limpio OK", flush=True)

        patrones = detect_pattern_24h_simple(ohlc)

        return path, min_p, max_p, patrones, ohlc
    except Exception as e:
        print(f">>> Error chart 24H 1H: {e}", flush=True)
        return None, 0, 0, [], []

# ---------------------------------------------------------------------------------
# BLOQUE 11: GRAFICO 30D - 1D - COMPLETO CON TODO - PARA CADA 15 DIAS
# ---------------------------------------------------------------------------------
def build_chart_30d_1d_pro():
    """
    QUE HACE: Grafico 30 dias en velas de 1 dia, CON TODO como pediste cada 15 dias:
    - Rango, RSI, cruce medias, patron importante
    - 2 subgraficos: precio arriba, RSI abajo
    """
    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440" # 1440 = 1 dia
        data = requests.get(url, timeout=15).json()
        ohlc = list(data["result"]["XXBTZUSD"])[-30:]
        times = [datetime.fromtimestamp(int(x[0]), tz=TZ) for x in ohlc]
        closes = [float(x[4]) for x in ohlc]; highs = [float(x[2]) for x in ohlc]; lows = [float(x[3]) for x in ohlc]
        opens = [float(x[1]) for x in ohlc]

        ma20 = [sum(closes[i-20:i])/20 if i>=20 else None for i in range(len(closes))]
        ma50 = [sum(closes[i-50:i])/50 if i>=50 else None for i in range(len(closes))] if len(closes)>=50 else [None]*len(closes)
        rsi = calc_rsi(closes)

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

        ax2.axhline(70, color='red', linestyle='--', alpha=0.5); ax2.axhline(30, color='green', linestyle='--', alpha=0.5)
        rsi_hist = [calc_rsi(closes[:i+1]) for i in range(len(closes))]
        ax2.plot(times, rsi_hist, color='#7B1FA2', linewidth=2)
        ax2.set_ylim(0,100); ax2.set_ylabel('RSI'); ax2.grid(alpha=0.3)
        estado = "SOBRECOMPRADO" if rsi>70 else "SOBREVENTA" if rsi<30 else "NEUTRAL"
        ax2.set_title(f"RSI 1D: {estado}")

        plt.xticks(rotation=15); plt.tight_layout()
        path = "/tmp/btc_30d_1d.png"
        plt.savefig(path, dpi=150); plt.close()
        print(">>> Grafico 30D 1D PRO OK", flush=True)

        patrones = detect_pattern_30d_pro(closes, highs, lows, rsi)

        return path, rsi, min_p, max_p, ma20[-1], patrones
    except Exception as e:
        print(f">>> Error chart 30D 1D: {e}", flush=True)
        return None, 50, 0, 0, 0, []

# ---------------------------------------------------------------------------------
# BLOQUE 12: NOTICIAS
# ---------------------------------------------------------------------------------
def get_filtered_news():
    try:
        url = "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&currencies=BTC&filter=hot"
        try:
            data = requests.get(url, timeout=10).json()
            news = data.get('results',[])[:10]
        except: return []
        data_mem = load_data(); seen = data_mem.get("seen_news",[]); alertas = []
        for n in news:
            title = (n.get('title','') or '').lower()
            news_id = n.get('id')
            if news_id in seen: continue
            if any(k in title for k in KEYWORDS_ALTA_VOLATILIDAD):
                alertas.append(n); seen.append(news_id)
                if len(seen)>100: seen = seen[-100:]
        data_mem["seen_news"]=seen; save_data(data_mem)
        return alertas
    except Exception as e:
        print(f">>> Error news: {e}", flush=True)
        return []

# ---------------------------------------------------------------------------------
# BLOQUE 13: JOB PRINCIPAL DIARIO - 8,13,18,23 - TU PETICION EXACTA
# ---------------------------------------------------------------------------------
def job_daily(with_chart=False, chart_type="24h"):
    """
    Esta funcion es la que se ejecuta a las 8,13,18,23.
    with_chart = True si tiene que mandar foto (solo 8 y 23)
    chart_type = "24h" para grafico 24H limpio 1H
    FLUJO ULTRA DETALLADO:
    1. Trae precio, 24h%, 7d% y closes para RSI
    2. Trae rango 24H (min/max ultimas 24h)
    3. Calcula RSI 1D exacto en este momento
    4. Trae sentimiento actual vs hace 7 dias
    5. Calcula % ultimo aviso
    6. Arma mensaje con \n\n (doble salto) para que se vea super separado
    7. Si with_chart True, genera grafico 24H 1H limpio + patrones simples
    8. Manda mensaje y luego foto si toca
    """
    print(f">>> job_daily INICIADO chart={with_chart} type={chart_type} {datetime.now(TZ)}", flush=True)
    price, change24, change7, closes_diario = get_price_full()
    if not price:
        send_text("⚠️ Bot BTC: API caida")
        return

    data = load_data()
    last_aviso = data.get("last_aviso_price", price)
    change_aviso = ((price-last_aviso)/last_aviso*100) if last_aviso else 0

    def fmt(c): return f"{'📈' if c>=0 else '📉'} {c:+.2f}%" # Funcion interna que formatea % con icono

    rsi_1d = calc_rsi(closes_diario) # RSI 1D exacto ahora
    rsi_1d_txt = f"{rsi_1d:.0f} {'🔥 Sobrecomprado' if rsi_1d>70 else '🧊 Sobreventa' if rsi_1d<30 else '⚖️ Neutral'}"

    min_24h, max_24h, candles_24h = get_range_24h() # Rango 24H que pediste
    rango_24h_txt = f"📊 Rango 24H: ${min_24h:,.0f} - ${max_24h:,.0f}" if min_24h else "📊 Rango 24H: --"

    sentiment = get_sentiment_week() # Sentimiento actual vs 7d

    # Mensaje super separado con \n\n como pediste
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
        # Añade patrones al mensaje si hay
        if patrones:
            msg += f"\n🔍 *Patron 24H:*\n\n" + "\n\n".join([f"• {p}" for p in patrones]) + "\n"

    # Envia mensaje primero
    send_text(msg)

    # Luego foto si toca (8 y 23)
    if with_chart and chart_path:
        send_photo(chart_path, f"📊 BTC 24H (1H) ${price:,.2f} | {rango_24h_txt}")

    data["last_aviso_price"] = price
    data["last_price"] = price
    save_data(data)
    check_custom_alerts(price)

# ---------------------------------------------------------------------------------
# BLOQUE 14: JOB CADA 15 DIAS A LAS 0:00 - TU PETICION
# ---------------------------------------------------------------------------------
def job_15dias():
    """
    Cada 15 dias a las 0:00 (dia 1 y 15 de cada mes) manda mensaje + grafico 30D 1D completo
    con rango, RSI, cruce medias, patron
    """
    print(f">>> job_15dias INICIADO {datetime.now(TZ)}", flush=True)
    price, change24, change7, closes_diario = get_price_full()
    if not price:
        send_text("⚠️ Bot BTC: API caida reporte 15 dias")
        return

    data = load_data()
    last_aviso = data.get("last_aviso_price", price)
    change_aviso = ((price-last_aviso)/last_aviso*100) if last_aviso else 0

    def fmt(c): return f"{'📈' if c>=0 else '📉'} {c:+.2f}%"

    # Grafico 30D pro con todo
    path, rsi_30d, min_30d, max_30d, ma20, patrones_30d = build_chart_30d_1d_pro()

    rsi_txt = f"{rsi_30d:.0f} {'🔥 Sobrecomprado' if rsi_30d>70 else '🧊 Sobreventa' if rsi_30d<30 else '⚖️ Neutral'}"
    rango_24h_min, rango_24h_max, _ = get_range_24h()
    rango_24h_txt = f"📊 Rango 24H: ${rango_24h_min:,.0f} - ${rango_24h_max:,.0f}" if rango_24h_min else "📊 Rango 24H: --"
    rango_30d_txt = f"📊 Rango 30D: ${min_30d:,.0f} - ${max_30d:,.0f}" if min_30d else "📊 Rango 30D: --"
    sentiment = get_sentiment_week()

    price_big = f"💰 *₿ BTC ${price:,.2f}* 💰"

    msg = (
        f"📅 *REPORTE CADA 15 DIAS - 30D*\n\n"
        f"{price_big}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"🔄 Último aviso: {fmt(change_aviso)}\n\n"
        f"🕐 24h: {fmt(change24)}\n\n"
        f"📅 7d: {fmt(change7)}\n\n"
        f"{rango_24h_txt}\n\n"
        f"{rango_30d_txt}\n\n"
        f"📈 RSI 1D: {rsi_txt}\n\n"
        f"🔍 *Analisis 30D:*\n\n" + "\n\n".join([f"• {p}" for p in patrones_30d]) + "\n\n"
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

# ---------------------------------------------------------------------------------
# BLOQUE 15: ALERTAS VOLATILIDAD Y PERSONALIZADAS - SE QUEDA IGUAL QUE YA FUNCIONA
# ---------------------------------------------------------------------------------
def check_volatility():
    data = load_data(); last = data.get("last_price",0)
    price, c24, _, _ = get_price_full()
    if not price or not last:
        data["last_price"]=price; save_data(data); return
    change = ((price-last)/last*100)
    if abs(change) >= 5:
        signo = "🚀 SUBIDÓN" if change>0 else "💥 CRASH"
        send_text(f"⚠️ *ALERTA VOLATILIDAD {signo}*\n\n₿ BTC ${price:,.2f} ({change:+.2f}% en 5 min)")
        data["last_price"]=price; save_data(data)
    else:
        if abs(change) > 0.5:
            data["last_price"]=price; save_data(data)

def check_custom_alerts(current_price):
    data = load_data(); alerts = data.get("alerts",[]); restantes = []
    for a in alerts:
        try:
            tipo = a["type"]; valor = a["value"]; chat = a.get("chat_id", CHAT_ID)
            if (tipo==">" and current_price>=valor) or (tipo=="<" and current_price<=valor):
                send_text(f"🔔 *ALERTA PERSONALIZADA*\n\nBTC ha cruzado {'por arriba' if tipo=='>' else 'por abajo'} de ${valor:,.2f}\n\nAhora: ${current_price:,.2f}", chat_id=chat)
            else: restantes.append(a)
        except: pass
    data["alerts"]=restantes; save_data(data)

def check_news_job():
    news = get_filtered_news()
    for n in news[:1]:
        title = n.get('title',''); url = n.get('url','')
        send_text(f"🗞️ *NOTICIA DE ALTO IMPACTO BTC*\n\n{title}\n\n{url}")

# ---------------------------------------------------------------------------------
# BLOQUE 16: RUTAS WEB
# ---------------------------------------------------------------------------------
@app.route('/')
def home(): return f"Bot running! Token:{bool(TOKEN)} Chat:{bool(CHAT_ID)}"

@app.route('/test') # /test = fuerza aviso 8:00 y 23:00 (24H 1H limpio)
def test():
    job_daily(True, "24h")
    return "Test 24H 1H enviado!"

@app.route('/test30d') # /test30d = fuerza reporte 15 dias (30D 1D pro)
def test30d():
    job_15dias()
    return "Test 30D 1D enviado!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if "message" not in data or "text" not in data["message"]: return "ok",200
        chat_id = data["message"]["chat"]["id"]
        text_raw = data["message"]["text"]
        text = text_raw.lower()
        print(f">>> Mensaje: {text}", flush=True)

        if "/start" in text or "/help" in text:
            send_text(
                "🤖 *Ferrari Bot v5 FINAL*\n\n"
                "*Avisos automaticos:*\n\n"
                "8:00 y 23:00 -> Mensaje + Grafico 24H (1H limpio) + patron\n\n"
                "13:00 y 18:00 -> Solo mensaje\n\n"
                "Dia 1 y 15 a las 0:00 -> Mensaje + Grafico 30D (1D) con RSI, medias y patron\n\n"
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
                "📊 *¿Que grafico quieres?*\n\n"
                "/grafico1h -> 24H en velas 1H limpio (sin RSI ni medias) + patron importante\n\n"
                "/grafico1d -> 30D en velas 1D con rango, RSI, cruce medias y patron\n\n"
                "Auto: 8 y 23h -> 1H limpio, dia 1 y 15 0:00 -> 30D pro",
                chat_id=chat_id)

        elif "grafico1h" in text:
            # Usuario pidio 1H limpio
            p,_,_,_ = get_price_full()
            path, min_p, max_p, patrones, _ = build_chart_24h_1h_clean()
            if path:
                txt_pat = "\n\n".join(patrones)
                send_photo(path, f"BTC 24H (1H) ${p:,.2f}\n\nRango ${min_p:,.0f}-${max_p:,.0f}\n\n{txt_pat}", chat_id=chat_id)
            else: send_text("Error grafico 1H", chat_id=chat_id)

        elif "grafico1d" in text or "grafico30d" in text:
            p,_,_,_ = get_price_full()
            path, rsi, min_p, max_p, ma20, patrones = build_chart_30d_1d_pro()
            if path:
                txt_pat = "\n\n".join(patrones)
                send_photo(path, f"BTC 30D (1D) ${p:,.2f} RSI {rsi:.0f}\n\nRango ${min_p:,.0f}-${max_p:,.0f}\n\n{txt_pat}", chat_id=chat_id)
            else: send_text("Error grafico 30D", chat_id=chat_id)

        elif "grafico" in text:
            send_text("Escribe /grafico para elegir 1H o 1D", chat_id=chat_id)

        elif "/alerta" in text:
            m = re.search(r'([<>])\s*(\d+)', text_raw)
            if m:
                tipo=m.group(1); valor=float(m.group(2))
                d=load_data(); d["alerts"].append({"type":tipo,"value":valor,"chat_id":chat_id}); save_data(d)
                send_text(f"✅ Alerta creada: te aviso cuando BTC {tipo} ${valor:,.0f}", chat_id=chat_id)
            else: send_text("Usa: /alerta >95000 o /alerta <80000", chat_id=chat_id)

        elif "misalertas" in text:
            d=load_data(); al = [a for a in d.get("alerts",[]) if a.get("chat_id")==chat_id]
            if not al: send_text("No tienes alertas", chat_id=chat_id)
            else:
                txt = "\n\n".join([f"{a['type']} ${a['value']}" for a in al])
                send_text(f"🔔 Tus alertas:\n\n{txt}\n\nBorra con /borraralertas", chat_id=chat_id)

        elif "borraralertas" in text:
            d=load_data(); d["alerts"]=[a for a in d["alerts"] if a.get("chat_id")!=chat_id]; save_data(d)
            send_text("🗑️ Alertas borradas", chat_id=chat_id)

        elif "sentimiento" in text:
            send_text(get_sentiment_week(), chat_id=chat_id)

        elif "noticias" in text:
            n = get_filtered_news()
            if not n: send_text("No hay noticias de alto impacto ahora", chat_id=chat_id)
            else: send_text(f"🗞️ {n[0]['title']}\n\n{n[0]['url']}", chat_id=chat_id)

        else:
            p,c24,_,_ = get_price_full()
            send_text(f"Escribe /grafico para elegir 1H o 1D\n\nBTC ${p:,.2f}", chat_id=chat_id)

    except Exception as e: print(f">>> Error webhook: {e}", flush=True)
    return "ok",200

# ---------------------------------------------------------------------------------
# BLOQUE 17: DESPERTADORES - HORARIO EXACTO QUE PEDISTE
# ---------------------------------------------------------------------------------
# cron hour=8 minute=0 = todos los dias a las 8:00
# cron day='1,15' hour=0 minute=0 = dias 1 y 15 de cada mes a las 0:00 (cada 15 dias)
# interval minutes=5 = cada 5 minutos
scheduler=BackgroundScheduler(timezone=TZ, daemon=True)

# 8:00 y 23:00 -> mensaje + grafico 24H 1H limpio sin RSI ni medias + patron
scheduler.add_job(lambda: job_daily(True, "24h"), 'cron', hour=8, minute=0, id="btc8")
scheduler.add_job(lambda: job_daily(False, "24h"), 'cron', hour=13, minute=0, id="btc13")
scheduler.add_job(lambda: job_daily(False, "24h"), 'cron', hour=18, minute=0, id="btc18")
scheduler.add_job(lambda: job_daily(True, "24h"), 'cron', hour=23, minute=0, id="btc23")

# Cada 15 dias a las 0:00 -> dia 1 y 15 de cada mes
scheduler.add_job(job_15dias, 'cron', day='1,15', hour=0, minute=0, id="cada15dias")

# Volatilidad y noticias (lo dejamos igual que ya funciona)
scheduler.add_job(check_volatility, 'interval', minutes=5, id="vol")
scheduler.add_job(check_news_job, 'interval', minutes=10, id="news")

scheduler.start()
print(">>> Scheduler v5 FINAL: 8(24H),13,18,23(24H) + cada 15 dias 0:00 30D + vol 5m + news 10m", flush=True)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
