import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import pandas_ta as ta
from urllib.parse import urlencode
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- FLASK SUNUCUSU (RENDER İÇİN) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot aktif ve calisiyor!"

def run():
    # Render'ın atadığı portu al, yoksa 10000 kullan
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- MEVCUT AYARLARIN VE FONKSİYONLARIN ---
load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Strateji Ayarları (Aynı kalabilir)
DUSUS_ESIGI = -10.0
MIN_HACIM = 2000000
ALIM_BUT_USDT = 20
STOP_LOSS_PCT = 1.5
TRAILING_STEP = 0.5
ZAMAN_LIMITI = 86400

# [Buradaki telegram_gonder, binance_istek ve teknik_analiz_yap fonksiyonlarını aynen koru]
def telegram_gonder(mesaj):
    if not TG_TOKEN: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": mesaj, "parse_mode": "HTML"})
    except: pass

def binance_istek(method, endpoint, params={}):
    params['timestamp'] = int(time.time() * 1000)
    query = urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params['signature'] = signature
    headers = {'X-MBX-APIKEY': API_KEY}
    url = f"https://api.binance.com{endpoint}"
    if method == "POST":
        return requests.post(url, params=params, headers=headers).json()
    return requests.get(url, params=params, headers=headers).json()

def teknik_analiz_yap(symbol):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines", 
                         params={"symbol": symbol, "interval": "1h", "limit": 50}).json()
        df = pd.DataFrame(r, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tb', 'tg', 'i'])
        df['c'] = df['c'].astype(float)
        rsi = ta.rsi(df['c'], length=14).iloc[-1]
        son_fiyatlar = df['c'].tail(3)
        oynaklik = (son_fiyatlar.max() - son_fiyatlar.min()) / son_fiyatlar.min() * 100
        return rsi, oynaklik
    except: return None, None

def firsat_bul():
    tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr").json()
    adaylar = []
    for t in tickers:
        symbol = t['symbol']
        try:
            degisim = float(t['priceChangePercent'])
            hacim = float(t['quoteVolume'])
            if symbol.endswith('USDT') and degisim <= DUSUS_ESIGI and hacim >= MIN_HACIM:
                rsi, oynaklik = teknik_analiz_yap(symbol)
                if rsi and rsi < 35 and oynaklik < 1.2:
                    adaylar.append({"symbol": symbol, "price": float(t['lastPrice']), "rsi": rsi})
        except: continue
    return sorted(adaylar, key=lambda x: x['rsi'])[0] if adaylar else None

# --- MAIN DÖNGÜSÜ ---
def main():
    # Flask sunucusunu başlat
    keep_alive()
    
    aktif_pozisyon = None
    giris_fiyati = 0
    en_yuksek_fiyat = 0
    giris_zamani = 0

    telegram_gonder("🤖 <b>Bot Başlatıldı!</b>\nRender üzerinde aktif.")

    while True:
        try:
            # [Buradaki alım-satım mantığını aynen koru]
            # ... (Senin paylaştığın while True döngüsü içeriği)
            time.sleep(60)
        except Exception as e:
            print(f"Hata: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
