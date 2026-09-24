# ============================================================
# IMPORTS - Las herramientas que le damos al bot
# ============================================================
import os # os = Operating System. Sirve para leer variables secretas de Render (TOKEN)
import requests # requests = Para hacer llamadas a internet (Kraken, Telegram)
import json # json = Para guardar memoria en un archivo.json (como un txt organizado)
import re # re = Regular Expressions. Para entender si el usuario escribe "> 90000"
from datetime import datetime, timedelta # datetime = Para saber que hora es en España
from zoneinfo import ZoneInfo # ZoneInfo = Para poner zona horaria Europe/Madrid
from flask import Flask, request # Flask = Crea una mini pagina web. Render necesita esto para que el bot este "Live"
from apscheduler.schedulers.background import BackgroundScheduler # BackgroundScheduler = Un despertador que ejecuta cosas a las 8,13,18,23 sin parar
import matplotlib # matplotlib = Para dibujar graficos
matplotlib.use('Agg') # Agg = Le decimos "dibuja sin pantalla", porque en Render no hay pantalla
import matplotlib.pyplot as plt # plt = El pintor que dibuja las velas

# ============================================================
# CONFIGURACION - Tus llaves secretas
# ============================================================
# os.environ.get = Lee lo que pusiste en Render > Environment > TELEGRAM_TOKEN
#.strip() = Quita espacios por si copiaste mal el token
TOKEN = os.environ.get("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.environ.get("CHAT_ID","").strip()
TZ = ZoneInfo("Europe/Madrid") # TZ = TimeZone. Toda la hora del bot sera hora de España
DATA_FILE = "/tmp/bot_data.json" # Donde guardamos memoria. /tmp es gratis pero se borra si Render reinicia
app = Flask(__name__) # __name__ = Crea la app web de Flask. Es obligatorio.

# Estas palabras son las UNICAS que hacen que BTC se mueva 3% en 5 minutos.
# Si no filtramos, te llegarian 100 noticias al dia. Asi solo 2-3 importantes.
KEYWORDS_ALTA_VOLATILIDAD = [
    "trump", "musk", "saylor", "warsh", # Personas que mueven mercado con un tuit
    "sec", "etf", "fed", "federal reserve", "reserva federal", # Regulacion de USA
    "ban", "banea", "prohibe", "aprueba", "hack", "hackea", "crash", "guerra", "war" # Verbos de panico
]

# ============================================================
# MEMORIA - Como el bot recuerda cosas
# ============================================================
def load_data():
    """Esta funcion es como abrir un cuaderno. Si existe lo lee, si no crea uno nuevo."""
    try: # try = Intenta hacer esto, si falla no rompas el bot
        with open(DATA_FILE, 'r') as f: # open 'r' = read = leer archivo
            return json.load(f) # json.load = Convierte el texto del archivo en diccionario de Python
    except: # Si el archivo no existe (primera vez que arranca)
        # Devolvemos memoria vacia con valores por defecto
        return {"last_price": 0, "last_aviso_price": 0, "alerts": [], "seen_news": []}

def save_data(data):
    """Esta funcion es como guardar el cuaderno."""
    try:
        with open(DATA_FILE, 'w') as f: # 'w' = write = escribir
            json.dump(data, f) # json.dump = Guarda el diccionario como texto
    except Exception as e:
        print(f">>> Error guardando data: {e}", flush=True) # flush=True = que se vea en Logs de Render al instante

# ============================================================
# TELEGRAM - Como habla el bot
# ============================================================
def send_text(msg, chat_id=None):
    """Manda un mensaje de texto a Telegram"""
    try:
        # Esta es la URL oficial de Telegram para mandar mensajes. TOKEN es tu llave
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        # requests.post = Hace una llamada POST (como rellenar un formulario)
        r = requests.post(url,
            json={ # json = lo que le mandamos a Telegram
                "chat_id": chat_id or CHAT_ID, # chat_id or CHAT_ID = Si me dices a quien responder, respondo a el, si no al CHAT_ID fijo
                "text": msg,
                "parse_mode": "Markdown", # Markdown = Para que **negrita** funcione
                "disable_web_page_preview": True # Para que no salga preview feo de links
            }, timeout=20)
        print(f">>> Telegram {r.status_code}", flush=True) # 200 = OK, 400 = error
        return True
    except Exception as e:
        print(f">>> ERROR Telegram: {e}", flush=True)
        return False

def send_photo(photo_path, caption="", chat_id=None):
    """Manda una foto (el grafico)"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as f: # 'rb' = read binary = leer foto en binario
            r = requests.post(url, data={"chat_id": chat_id or CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": f}, timeout=30)
        print(f">>> Foto {r.status_code}", flush=True)
    except Exception as e: print(f">>> Error foto: {e}", flush=True)

# ============================================================
# PRECIO - El corazon del bot. Ahora saca 24h y 7 dias
# ============================================================
def get_price_full():
    """
    Esta funcion devuelve 4 cosas:
    1. price = precio actual
    2. change_24h = cambio en 24h
    3. change_7d = cambio en 7 dias
    4. closes = lista de 200 precios para calcular RSI
    """
    price = None
    change_24h = 0.0
    change_7d = 0.0
    closes = []
    try:
        # Kraken OHLC = Open High Low Close. Intervalo 1440 = 1 dia = 1440 minutos
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"]) # candles = velas. Cada vela = [tiempo, apertura, max, min, cierre...]
        closes_daily = [float(c[4]) for c in candles] # c[4] = el cierre. float() convierte texto a numero
        if len(candles) >= 2:
            # Formula de porcentaje: (hoy - ayer) / ayer * 100
            change_24h = ((closes_daily[-1] - closes_daily[-2]) / closes_daily[-2]) * 100
        if len(candles) >= 8:
            change_7d = ((closes_daily[-1] - closes_daily[-8]) / closes_daily[-8]) * 100
        price = closes_daily[-1] # El precio actual es el ultimo cierre diario
        print(f">>> Kraken Diario OK 24h:{change_24h:.2f}% 7d:{change_7d:.2f}%", flush=True)
    except Exception as e: print(f">>> Error Kraken diario: {e}", flush=True)

    # Si falla, Plan B: Ticker rapido de Kraken
    if not price:
        try:
            j = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=10).json()
            price = float(j["result"]["XXBTZUSD"]["c"][0]) # c[0] = ultimo precio cerrado
        except: pass # pass = no hagas nada, sigue

    # Plan C: Binance si Kraken muere
    if not price:
        try:
            j = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=10, headers={"User-Agent":"Mozilla/5.0"}).json()
            price = float(j.get("lastPrice",0))
            change_24h = float(j.get("priceChangePercent",0))
        except: pass

    # Para RSI necesitamos 200 velas
    try:
        j = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440", timeout=15).json()
        candles = list(j["result"]["XXBTZUSD"])
        closes = [float(c[4]) for c in candles][-200:] # [-200:] = coge las ultimas 200
    except: closes = []

    return price, change_24h, change_7d, closes

# ============================================================
# SENTIMIENTO - Compara hoy vs hace 1 semana
# ============================================================
def get_sentiment_week():
    try:
        # alternative.me/fng = Fear and Greed Index. limit=7 = trae 7 dias
        d = requests.get("https://api.alternative.me/fng/?limit=7", timeout=10).json()['data']
        hoy = int(d[0]['value']) # d[0] = hoy
        hace7 = int(d[6]['value']) # d[6] = hace 7 dias
        diff = hoy - hace7 # diff = diferencia
        # Operador ternario: emoji = "😱" si hoy<25 sino "😨" si hoy<45 sino...
        emoji="😱" if hoy<25 else "😨" if hoy<45 else "😐" if hoy<55 else "🤑" if hoy<75 else "🤩"
        tendencia = "🔼 sube" if diff>5 else "🔽 baja" if diff<-5 else "➡️ estable"
        return f"{emoji} *Fear & Greed {hoy}/100* ({d[0]['value_classification']})\n Hace 7d: {hace7}/100 ({tendencia} {diff:+d})"
    except: return "Sentimiento: --"

# ============================================================
# RSI - Indice que te dice si es momento de comprar/vender
# ============================================================
def calc_rsi(prices, period=14):
    """RSI = Relative Strength Index. Mide si la gente ha comprado demasiado (>70) o vendido demasiado (<30)"""
    if len(prices) < period+1: return 50 # Si no hay datos suficientes, devuelve 50 (neutral)
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))] # deltas = cambios dia a dia
    gains = [d if d>0 else 0 for d in deltas[-period:]] # gains = solo las ganancias
    losses = [-d if d<0 else 0 for d in deltas[-period:]] # losses = solo las perdidas (en positivo)
    avg_gain = sum(gains)/period # media de ganancias
    avg_loss = sum(losses)/period # media de perdidas
    if avg_loss == 0: return 100 # Si no hubo perdidas, RSI = 100
    rs = avg_gain/avg_loss # RS = fuerza relativa
    rsi = 100 - (100/(1+rs)) # Formula oficial de RSI
    return rsi

# ============================================================
# GRAFICO PRO - Con rango, tendencia y RSI
# ============================================================
def build_chart_image():
    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440"
        data = requests.get(url, timeout=15).json()
        ohlc = list(data["result"]["XXBTZUSD"])[-30:] # 30 dias para que se vea tendencia

        times = [datetime.fromtimestamp(int(x[0]), tz=TZ) for x in ohlc] # Convierte timestamp a fecha España
        closes = [float(x[4]) for x in ohlc]
        highs = [float(x[2]) for x in ohlc]
        lows = [float(x[3]) for x in ohlc]

        # MA20 = Media Movil de 20 dias. Si precio > MA20 = alcista
        ma20 = [sum(closes[i-20:i])/20 if i>=20 else None for i in range(len(closes))]
        rsi = calc_rsi(closes)

        # plt.subplots(2,1) = Crea 2 graficos uno encima de otro. height_ratios = el de arriba 3 veces mas grande
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10,6), gridspec_kw={'height_ratios':[3,1]})

        # Dibuja cada vela
        for i in range(len(ohlc)):
            color = '#26a69a' if closes[i] >= float(ohlc[i][1]) else '#ef5350' # verde si sube, rojo si baja
            ax1.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1) # mecha
            ax1.plot([times[i], times[i]], [float(ohlc[i][1]), closes[i]], color=color, linewidth=5) # cuerpo

        ax1.plot(times, ma20, color='#FFC107', linewidth=1.5, label='MA20 (tendencia)') # Linea amarilla tendencia

        min_p = min(lows); max_p = max(highs) # min y max del mes
        ax1.set_title(f"BTC 30D | Rango ${min_p:,.0f} - ${max_p:,.0f} | RSI {rsi:.1f}", fontsize=11, fontweight='bold')
        ax1.legend(); ax1.grid(alpha=0.3) # alpha = transparencia

        # Grafico RSI abajo
        ax2.axhline(70, color='red', linestyle='--', alpha=0.5); ax2.axhline(30, color='green', linestyle='--', alpha=0.5) # Lineas 70 y 30
        rsi_hist = [calc_rsi(closes[:i+1]) for i in range(len(closes))] # Calcula RSI cada dia para dibujar historico
        ax2.plot(times, rsi_hist, color='#7B1FA2', linewidth=2)
        ax2.set_ylim(0,100); ax2.set_ylabel('RSI'); ax2.grid(alpha=0.3)
        estado = "SOBRECOMPRADO" if rsi>70 else "SOBREVENTA" if rsi<30 else "NEUTRAL"
        ax2.set_title(f"RSI 1D: {estado}")

        plt.xticks(rotation=15); plt.tight_layout() # rotation = gira fechas para que se lean
        path = "/tmp/btc.png"
        plt.savefig(path, dpi=150); plt.close() # Guarda y cierra para no gastar memoria
        print(">>> Grafico PRO OK", flush=True)
        return path, rsi, min_p, max_p, ma20[-1] # ma20[-1] = ultimo valor de MA20
    except Exception as e:
        print(f">>> Error chart PRO: {e}", flush=True)
        return None, 50, 0, 0, 0

# ============================================================
# NOTICIAS FILTRADAS
# ============================================================
def get_filtered_news():
    """Solo devuelve noticias que contienen palabras clave de alto impacto"""
    try:
        url = "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&currencies=BTC&filter=hot"
        try:
            data = requests.get(url, timeout=10).json()
            news = data.get('results',[])[:10] # Solo las 10 mas calientes
        except: return []

        data_mem = load_data()
        seen = data_mem.get("seen_news",[])
        alertas = []

        for n in news:
            title = (n.get('title','') or '').lower() # lower() = todo a minusculas para comparar
            news_id = n.get('id')
            if news_id in seen: continue # Si ya la vimos, saltar
            if any(k in title for k in KEYWORDS_ALTA_VOLATILIDAD): # any() = si alguna palabra clave esta en el titulo
                alertas.append(n)
                seen.append(news_id)
                if len(seen)>100: seen = seen[-100:]

        data_mem["seen_news"]=seen
        save_data(data_mem)
        return alertas
    except Exception as e:
        print(f">>> Error news: {e}", flush=True)
        return []

# ============================================================
# JOB PRINCIPAL - Lo que pasa a las 8,13,18,23
# ============================================================
def job_scheduled(with_chart=False):
    print(f">>> job INICIADO chart={with_chart} {datetime.now(TZ)}", flush=True)
    price, change24, change7, closes = get_price_full()
    if not price:
        send_text("⚠️ Bot BTC: API caida")
        return

    data = load_data()
    last_aviso = data.get("last_aviso_price", price)
    # Calcula cambio desde ultimo aviso
    change_aviso = ((price-last_aviso)/last_aviso*100) if last_aviso else 0

    price_big = f"💰 *₿ BTC ${price:,.2f}* 💰" # * * = negrita en Markdown

    def fmt(c): return f"{'📈' if c>=0 else '📉'} {c:+.2f}%" # Funcion interna para formatear % con icono
    txt_aviso = fmt(change_aviso)
    txt_24 = fmt(change24)
    txt_7 = fmt(change7)

    sentiment = get_sentiment_week()
    chart_path, rsi, min_p, max_p, ma = build_chart_image() if with_chart else (None, calc_rsi(closes), 0,0,0)
    rsi_txt = f"RSI 1D: {rsi:.0f} {'🔥 Sobrecomprado' if rsi>70 else '🧊 Sobreventa' if rsi<30 else '⚖️ Neutral'}"
    tendencia = "Alcista" if price>ma else "Bajista" # Si precio > media movil, tendencia alcista

    msg = (
        f"{price_big}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔄 Último aviso: {txt_aviso}\n"
        f"🕐 24h: {txt_24} | 📅 7d: {txt_7}\n"
        f"📊 Rango 30D: ${min_p:,.0f} - ${max_p:,.0f} | Tendencia {tendencia} (MA20 ${ma:,.0f})\n"
        f"📈 {rsi_txt}\n"
        f"{sentiment}\n"
        f"📅 {datetime.now(TZ).strftime('%d/%m %H:%M')} España"
    )
    send_text(msg)

    if with_chart and chart_path:
        send_photo(chart_path, f"📊 BTC ${price:,.2f} | RSI {rsi:.0f} | {tendencia}")

    data["last_aviso_price"] = price
    data["last_price"] = price
    save_data(data)
    check_custom_alerts(price)

# ============================================================
# ALERTAS: 5% INSTANTANEO
# ============================================================
def check_volatility():
    """Esta se ejecuta cada 5 minutos. Es tu detector de crash/pump"""
    data = load_data()
    last = data.get("last_price",0)
    price, c24, _, _ = get_price_full()
    if not price or not last:
        data["last_price"]=price; save_data(data); return
    change = ((price-last)/last*100)
    if abs(change) >= 5: # abs() = valor absoluto. Si se mueve 5% en cualquier direccion
        signo = "🚀 SUBIDÓN" if change>0 else "💥 CRASH"
        send_text(f"⚠️ *ALERTA VOLATILIDAD {signo}*\n₿ BTC ${price:,.2f} ({change:+.2f}% en 5 min)\nEsto no es el aviso de las 8,13,18,23h, es movimiento brusco!")
        data["last_price"]=price
        save_data(data)
    else:
        if abs(change) > 0.5:
            data["last_price"]=price; save_data(data)

def check_custom_alerts(current_price):
    """Revisa si alguna alerta personalizada del usuario se cumplio"""
    data = load_data()
    alerts = data.get("alerts",[])
    restantes = [] # Las que aun no se cumplieron
    for a in alerts:
        try:
            tipo = a["type"]; valor = a["value"]; chat = a.get("chat_id", CHAT_ID)
            if (tipo==">" and current_price>=valor) or (tipo=="<" and current_price<=valor):
                send_text(f"🔔 *ALERTA PERSONALIZADA*\nBTC ha cruzado {'por arriba' if tipo=='>' else 'por abajo'} de ${valor:,.2f}\nAhora: ${current_price:,.2f}", chat_id=chat)
            else:
                restantes.append(a) # Si no se cumple, la guardamos para la proxima
        except: pass
    data["alerts"]=restantes
    save_data(data)

def check_news_job():
    news = get_filtered_news()
    for n in news[:1]: # [:1] = solo la primera para no spamear
        title = n.get('title','')
        url = n.get('url','')
        send_text(f"🗞️ *NOTICIA DE ALTO IMPACTO BTC*\n{title}\n{url}\n\n_Filtrado por: Trump/Musk/Saylor/FED/SEC/ETF_")

# ============================================================
# RUTAS WEB - Para que Render y Telegram hablen con tu bot
# ============================================================
@app.route('/') # Cuando entras a tu-url.onrender.com/
def home(): return f"Bot running! Token:{bool(TOKEN)} Chat:{bool(CHAT_ID)}"

@app.route('/test') # Cuando entras a tu-url.onrender.com/test -> fuerza un aviso
def test():
    job_scheduled(True)
    return "Test enviado!"

@app.route('/webhook', methods=['POST']) # Telegram manda aqui cada mensaje que le escribes al bot
def webhook():
    try:
        data = request.get_json() # get_json = lee lo que manda Telegram
        if "message" not in data or "text" not in data["message"]: return "ok",200
        chat_id = data["message"]["chat"]["id"]
        text_raw = data["message"]["text"] # Texto original con mayusculas
        text = text_raw.lower() # lower = minusculas para comparar mas facil
        print(f">>> Mensaje: {text}", flush=True)

        if "/start" in text or "/help" in text:
            send_text("🤖 *Ferrari Bot v2 PRO*\n/precio - precio ahora\n/grafico - velas 30D + RSI + MA\n/alerta >90000 - alerta personalizada\n/alerta <80000\n/misalertas - ver alertas\n/sentimiento - Fear&Greed semana\n/noticias - forzar chequeo noticias", chat_id=chat_id)

        elif "/precio" in text:
            p,c24, c7, closes = get_price_full()
            d = load_data()
            last_aviso = d.get("last_aviso_price", p)
            ch_aviso = ((p-last_aviso)/last_aviso*100) if last_aviso else 0
            send_text(f"💰 *BTC ${p:,.2f}*\n🔄 Último aviso: {ch_aviso:+.2f}%\n🕐 24h: {c24:+.2f}% | 7d: {c7:+.2f}%", chat_id=chat_id)

        elif "grafico" in text or "gráfico" in text:
            p,c24,_,_ = get_price_full()
            path,rsi,_,_,_ = build_chart_image()
            if path: send_photo(path, f"BTC ${p:,.2f} RSI {rsi:.0f}", chat_id=chat_id)
            else: send_text("Error grafico", chat_id=chat_id)

        elif "/alerta" in text:
            # re.search = Busca patron > numero en el texto. Ej: ">90000"
            m = re.search(r'([<>])\s*(\d+)', text_raw)
            if m:
                tipo=m.group(1); valor=float(m.group(2))
                d=load_data()
                d["alerts"].append({"type":tipo,"value":valor,"chat_id":chat_id})
                save_data(d)
                send_text(f"✅ Alerta creada: te aviso cuando BTC {tipo} ${valor:,.0f}", chat_id=chat_id)
            else: send_text("Usa: /alerta >95000 o /alerta <80000", chat_id=chat_id)

        elif "misalertas" in text:
            d=load_data()
            al = [a for a in d.get("alerts",[]) if a.get("chat_id")==chat_id]
            if not al: send_text("No tienes alertas", chat_id=chat_id)
            else:
                txt = "\n".join([f"{a['type']} ${a['value']}" for a in al])
                send_text(f"🔔 Tus alertas:\n{txt}\nBorra con /borraralertas", chat_id=chat_id)

        elif "borraralertas" in text:
            d=load_data(); d["alerts"]=[a for a in d["alerts"] if a.get("chat_id")!=chat_id]; save_data(d)
            send_text("🗑️ Alertas borradas", chat_id=chat_id)

        elif "sentimiento" in text:
            send_text(get_sentiment_week(), chat_id=chat_id)

        elif "noticias" in text:
            n = get_filtered_news()
            if not n: send_text("No hay noticias de alto impacto ahora (Trump/Musk/FED/SEC)", chat_id=chat_id)
            else: send_text(f"🗞️ {n[0]['title']}\n{n[0]['url']}", chat_id=chat_id)

        else:
            p,c24,_,_ = get_price_full()
            send_text(f"Escribe /precio o /grafico\nBTC ${p:,.2f}", chat_id=chat_id)

    except Exception as e: print(f">>> Error webhook: {e}", flush=True)
    return "ok",200

# ============================================================
# DESPERTADORES - El horario del bot
# ============================================================
scheduler=BackgroundScheduler(timezone=TZ, daemon=True) # daemon=True = que se ejecute en segundo plano
# cron = tipo "todos los dias a las X"
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=8, minute=0, id="btc8") # lambda = funcion mini sin nombre
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=13, minute=0, id="btc13")
scheduler.add_job(lambda: job_scheduled(False), 'cron', hour=18, minute=0, id="btc18")
scheduler.add_job(lambda: job_scheduled(True), 'cron', hour=23, minute=0, id="btc23")
# interval = cada X minutos
scheduler.add_job(check_volatility, 'interval', minutes=5, id="vol") # Chequea crash 5%
scheduler.add_job(check_news_job, 'interval', minutes=10, id="news") # Chequea noticias
scheduler.start() # ¡Arranca todos los despertadores!
print(">>> Scheduler PRO iniciado: 8,13,18,23 + volatilidad 5m + noticias 10m", flush=True)

if __name__=="__main__":
    # Esto solo se ejecuta si lanzas el archivo directamente con python main.py
    # Render usa esto para arrancar tu web
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000))) # 0.0.0.0 = escucha en todas las IPs
