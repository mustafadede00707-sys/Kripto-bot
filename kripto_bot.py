import requests
import os

# --- DEBUG TESTİ BAŞLAT ---
try:
    current_ip = requests.get('https://api.ipify.org').text
    print(f"--- SISTEM KONTROL ---")
    print(f"BOTUN DIS IP ADRESI: {current_ip}")
    print(f"BINANCE IP LISTESINDEKIYLE AYNI MI?: {'Evet' if current_ip == '216.24.57.1' else 'HAYIR!'}")
    print(f"-----------------------")
except Exception as e:
    print(f"IP KONTROL HATASI: {e}")
# --- DEBUG TESTİ BİTTİ ---

import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- RENDER ALIVE MECHANISM ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running in FAST MODE!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- SETTINGS (HIZLI MOD) ---
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DUSUS_ESIGI = -7.0   # %7 ve üzeri düşüşleri yakala
MIN_HACIM = 1500000  # 1.5 Milyon USDT hacim
ALIM_BUT_USDT = 100
MAX_POZISYON = 3
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
        response = requests.request(method, url, params=params, headers=headers, timeout=15)
        return response.json()
    except: return {}

def hesapla_rsi(fiyatlar, period=14):
    if len(fiyatlar) <= period: return 50
    deltas = [fiyatlar[i+1] - fiyatlar[i] for i in range(len(fiyatlar)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0: return 100
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss
    return 100 - (100 / (100 + rs))

def teknik_analiz_yap(symbol):
    try:
        # HIZLI MOD: 1 saat yerine 15 dakikalık mumlar çekiliyor
        r = requests.get(f"https://api.binance.com/api/v3/klines", 
                         params={"symbol": symbol, "interval": "15m", "limit": 50}, timeout=10).json()
        kapanislar = [float(k[4]) for k in r]
        rsi = hesapla_rsi(kapanislar)
        son_3 = kapanislar[-3:]
        # Oynaklık eşiği biraz daha esnetildi
        oynaklik = (max(son_3) - min(son_3)) / min(son_3) * 100
        return rsi, oynaklik
    except: return None, None

def firsat_bul(mevcut_pozisyonlar):
    try:
        tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15).json()
        adaylar = []
        for t in tickers:
            symbol = t['symbol']
            if not symbol.endswith('USDT') or symbol in mevcut_pozisyonlar: continue
            
            degisim = float(t['priceChangePercent'])
            hacim = float(t['quoteVolume'])
            
            if degisim <= DUSUS_ESIGI and hacim >= MIN_HACIM:
                rsi, oynaklik = teknik_analiz_yap(symbol)
                # Kriterler HIZLI MOD için esnetildi: RSI < 45, Oynaklık < 3.0
                if rsi and rsi < 45 and oynaklik < 3.0: 
                    adaylar.append({"symbol": symbol, "price": float(t['lastPrice']), "rsi": rsi})
        
        print(f"🔍 Tarama bitti. Uygun aday sayısı: {len(adaylar)}")
        return sorted(adaylar, key=lambda x: x['rsi'])[0] if adaylar else None
    except: return None

# --- MAIN LOOP ---
def main():
    keep_alive()
    pozisyonlar = {}
    telegram_gonder("⚡ <b>HIZLI MOD Aktif!</b>\n15dk RSI ve %7 Düşüş Takibi Başladı.")

    while True:
        try:
            if len(pozisyonlar) < MAX_POZISYON:
                firsat = firsat_bul(list(pozisyonlar.keys()))
                if firsat:
                    res = binance_istek("POST", "/api/v3/order", {
                        "symbol": firsat['symbol'], "side": "BUY", "type": "MARKET", "quoteOrderQty": ALIM_BUT_USDT
                    })
                    if 'orderId' in res:
                        symbol = firsat['symbol']
                        fiyat = float(res['fills'][0]['price'])
                        pozisyonlar[symbol] = {"giris": fiyat, "en_yuksek": fiyat, "zaman": time.time()}
                        telegram_gonder(f"🚀 <b>HIZLI ALIM: {symbol}</b>\nFiyat: {fiyat}\nRSI: {firsat['rsi']:.2f}")

            # SATIŞ KONTROLÜ
            for symbol in list(pozisyonlar.keys()):
                ticker = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}").json()
                su_an = float(ticker['price'])
                data = pozisyonlar[symbol]
                
                if su_an > data['en_yuksek']: pozisyonlar[symbol]['en_yuksek'] = su_an
                
                guncel_stop = pozisyonlar[symbol]['en_yuksek'] * (1 - STOP_LOSS_PCT / 100)
                gecen_sure = time.time() - data['zaman']
                
                if su_an <= guncel_stop or gecen_sure >= ZAMAN_LIMITI:
                    hesap = binance_istek("GET", "/api/v3/account")
                    miktar = next(a['free'] for a in hesap['balances'] if a['asset'] == symbol.replace('USDT', ''))
                    res = binance_istek("POST", "/api/v3/order", {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": float(miktar)})
                    
                    if 'orderId' in res:
                        kar = ((su_an - data['giris']) / data['giris']) * 100
                        telegram_gonder(f"💰 <b>SATIŞ YAPILDI: {symbol}</b>\nKâr/Zarar: %{kar:.2f}")
                        del pozisyonlar[symbol]

            time.sleep(30) # Her 30 saniyede bir kontrol et
        except Exception as e:
            print(f"Hata: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # Botu ayrı bir kolda başlat
    bot_thread = Thread(target=main)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Web sunucusunu ana kolda başlat (Render bunu bekler)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

