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

# --- RENDER ALIVE MECHANISM ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- SETTINGS ---
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DUSUS_ESIGI = -10.0
MIN_HACIM = 2000000
ALIM_BUT_USDT = 20
STOP_LOSS_PCT = 1.5
ZAMAN_LIMITI = 86400

# --- FUNCTIONS ---
def telegram_gonder(mesaj):
    if not TG_TOKEN: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}, timeout=10)
    except: pass

def binance_istek(method, endpoint, params={}):
    params['timestamp'] = int(time.time() * 1000)
    query = urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params['signature'] = signature
    headers = {'X-MBX-APIKEY': API_KEY}
    url = f"https://api.binance.com{endpoint}"
    try:
        if method == "POST":
            return requests.post(url, params=params, headers=headers, timeout=15).json()
        return requests.get(url, params=params, headers=headers, timeout=15).json()
    except Exception as e:
        print(f"API Error: {e}")
        return {}

def teknik_analiz_yap(symbol):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines", 
                         params={"symbol": symbol, "interval": "1h", "limit": 50}, timeout=10).json()
        df = pd.DataFrame(r, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tb', 'tg', 'i'])
        df['c'] = df['c'].astype(float)
        rsi = ta.rsi(df['c'], length=14).iloc[-1]
        son_fiyatlar = df['c'].tail(3)
        oynaklik = (son_fiyatlar.max() - son_fiyatlar.min()) / son_fiyatlar.min() * 100
        return rsi, oynaklik
    except: return None, None

def firsat_bul():
    try:
        tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15).json()
        adaylar = []
        for t in tickers:
            symbol = t['symbol']
            degisim = float(t['priceChangePercent'])
            hacim = float(t['quoteVolume'])
            if symbol.endswith('USDT') and degisim <= DUSUS_ESIGI and hacim >= MIN_HACIM:
                rsi, oynaklik = teknik_analiz_yap(symbol)
                if rsi and rsi < 35 and oynaklik < 1.2:
                    adaylar.append({"symbol": symbol, "price": float(t['lastPrice']), "rsi": rsi})
        return sorted(adaylar, key=lambda x: x['rsi'])[0] if adaylar else None
    except: return None

# --- MAIN LOOP ---
def main():
    keep_alive()
    aktif_pozisyon = None
    giris_fiyati = 0
    en_yuksek_fiyat = 0
    giris_zamani = 0

    telegram_gonder("🤖 <b>Bot Başlatıldı!</b>\nRender üzerinde aktif.")

    while True:
        try:
            if not aktif_pozisyon:
                firsat = firsat_bul()
                if firsat:
                    res = binance_istek("POST", "/api/v3/order", {
                        "symbol": firsat['symbol'], "side": "BUY", "type": "MARKET", "quoteOrderQty": ALIM_BUT_USDT
                    })
                    if 'orderId' in res:
                        aktif_pozisyon = firsat['symbol']
                        giris_fiyati = float(res['fills'][0]['price'])
                        en_yuksek_fiyat = giris_fiyati
                        giris_zamani = time.time()
                        telegram_gonder(f"✅ <b>ALIM YAPILDI!</b>\nCoin: {aktif_pozisyon}\nFiyat: {giris_fiyati}")
            
            else:
                ticker = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={aktif_pozisyon}").json()
                su_an_fiyat = float(ticker['price'])
                gecen_sure = time.time() - giris_zamani
                
                if su_an_fiyat > en_yuksek_fiyat:
                    en_yuksek_fiyat = su_an_fiyat
                
                guncel_stop = en_yuksek_fiyat * (1 - STOP_LOSS_PCT / 100)
                
                satis_nedeni = None
                if su_an_fiyat <= guncel_stop:
                    satis_nedeni = "STOP LOSS / TRAILING"
                elif gecen_sure >= ZAMAN_LIMITI:
                    satis_nedeni = "24 SAAT DOLDU"

                if satis_nedeni:
                    hesap = binance_istek("GET", "/api/v3/account")
                    vize = [a for a in hesap['balances'] if a['asset'] == aktif_pozisyon.replace('USDT', '')][0]
                    miktar = float(vize['free'])
                    
                    res = binance_istek("POST", "/api/v3/order", {
                        "symbol": aktif_pozisyon, "side": "SELL", "type": "MARKET", "quantity": miktar
                    })
                    
                    kar_zarar = ((su_an_fiyat - giris_fiyati) / giris_fiyati) * 100
                    telegram_gonder(f"🚀 <b>SATIŞ YAPILDI!</b>\nNeden: {satis_nedeni}\nKâr/Zarar: %{kar_zarar:.2f}")
                    aktif_pozisyon = None

            time.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
