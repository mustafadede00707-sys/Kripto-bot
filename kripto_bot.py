import os
import time
import hmac
import hashlib
import requests
import math
from urllib.parse import urlencode
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# ============================================================
# RENDER WEB SERVER (Render'ın uyku moduna girmemesi için)
# ============================================================
app = Flask('')

@app.route('/')
def home():
    return "✅ Trading Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================================
# AYARLAR
# ============================================================
load_dotenv()
API_KEY    = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TG_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DUSUS_ESIGI   = -3.0       # %3 düşüş yeterli (daha fazla fırsat)
MIN_HACIM     = 1_000_000  # Minimum 1M USDT hacim
ALIM_USDT     = 50         # Her işlemde 50 USDT (daha az risk)
MAX_POZISYON  = 3          # Aynı anda max 3 açık pozisyon
STOP_LOSS_PCT = 3.0        # İz süren stop: en yüksekten %3 aşağı
ZAMAN_LIMITI  = 43200      # 12 saat sonra zorla çıkış
TARAMA_ARALIK = 30         # Her 30 saniyede bir tarama
RSI_ESIGI     = 45         # RSI < 45 (daha geniş alım bölgesi)
OYNAKLIK_ESIGI = 10.0      # Oynaklık < %10 (daha stabil coinler)

# ============================================================
# TELEGRAM
# ============================================================
def telegram_gonder(mesaj: str):
    """Telegram'a mesaj gönder. Hata olursa sessizce geç."""
    if not TG_TOKEN or not TG_CHAT_ID:
        print(f"[TG] {mesaj}")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": TG_CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=10
        )
        if not r.ok:
            print(f"[TG HATA] {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[TG EXCEPTION] {e}")

# ============================================================
# BİNANCE API
# ============================================================
BASE_URL = "https://api.binance.com"

def binance_istek(method: str, endpoint: str, params: dict = None) -> dict:
    """İmzalı Binance API isteği gönderir."""
    if params is None:
        params = {}

    if not API_KEY or not API_SECRET:
        print("[HATA] API_KEY veya API_SECRET tanımlı değil!")
        return {}

    params["timestamp"] = int(time.time() * 1000)
    query_string = urlencode(params)
    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    params["signature"] = signature

    headers = {"X-MBX-APIKEY": API_KEY}
    url = f"{BASE_URL}{endpoint}"

    try:
        response = requests.request(
            method, url,
            params=params,
            headers=headers,
            timeout=15
        )
        data = response.json()
        if "code" in data and data["code"] < 0:
            print(f"[BİNANCE HATA] {data.get('code')}: {data.get('msg')}")
        return data
    except Exception as e:
        print(f"[BİNANCE EXCEPTION] {e}")
        return {}

def sembol_bilgisi_al(symbol: str) -> dict:
    """Exchange info'dan LOT_SIZE adım büyüklüğünü alır."""
    try:
        r = requests.get(
            f"{BASE_URL}/api/v3/exchangeInfo",
            params={"symbol": symbol},
            timeout=10
        ).json()
        for filtre in r["symbols"][0]["filters"]:
            if filtre["filterType"] == "LOT_SIZE":
                return {
                    "stepSize": float(filtre["stepSize"]),
                    "minQty":   float(filtre["minQty"])
                }
    except Exception as e:
        print(f"[LOT_SIZE HATA] {symbol}: {e}")
    return {"stepSize": 0.001, "minQty": 0.001}

def miktari_formatla(miktar: float, step_size: float) -> float:
    """Binance LOT_SIZE kuralına göre miktarı yuvarlar."""
    if step_size <= 0:
        return miktar
    precision = int(round(-math.log10(step_size)))
    factor = 10 ** precision
    return math.floor(miktar * factor) / factor

def serbest_miktar_al(asset: str) -> float:
    """Hesaptaki serbest coin miktarını döner."""
    hesap = binance_istek("GET", "/api/v3/account")
    if not hesap or "balances" not in hesap:
        print(f"[HATA] Hesap bilgisi alınamadı.")
        return 0.0
    for b in hesap["balances"]:
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0

# ============================================================
# TEKNİK ANALİZ
# ============================================================
def hesapla_rsi(fiyatlar: list, period: int = 14) -> float:
    """Wilder yöntemiyle RSI hesaplar."""
    if len(fiyatlar) <= period:
        return 50.0
    deltas = [fiyatlar[i+1] - fiyatlar[i] for i in range(len(fiyatlar)-1)]
    gains  = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        return 100.0

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def teknik_analiz_yap(symbol: str):
    """
    15 dakikalık mum verisiyle RSI ve kısa vadeli oynaklık hesaplar.
    Dönen: (rsi, oynaklik) veya (None, None)
    """
    try:
        r = requests.get(
            f"{BASE_URL}/api/v3/klines",
            params={"symbol": symbol, "interval": "15m", "limit": 50},
            timeout=10
        ).json()
        if not isinstance(r, list) or len(r) < 20:
            return None, None
        kapanislar = [float(k[4]) for k in r]
        rsi = hesapla_rsi(kapanislar)
        son_3 = kapanislar[-3:]
        oynaklik = (max(son_3) - min(son_3)) / min(son_3) * 100
        return rsi, round(oynaklik, 4)
    except Exception as e:
        print(f"[TEKNİK ANALİZ HATA] {symbol}: {e}")
        return None, None

# ============================================================
# FIRSAT TARAMA
# ============================================================
def firsat_bul(mevcut_semboller: list):
    """
    Tüm USDT çiftlerini tarayarak kriterlere uyan en iyi fırsatı bulur.
    Kriterler:
      - 24s fiyat değişimi <= DUSUS_ESIGI (%3 düşüş)
      - Hacim >= MIN_HACIM (1M USDT)
      - RSI < 45
      - Kısa vadeli oynaklık < %10
    """
    try:
        tickers = requests.get(
            f"{BASE_URL}/api/v3/ticker/24hr",
            timeout=15
        ).json()

        if not isinstance(tickers, list):
            print(f"[TARAMA HATA] Ticker verisi alınamadı.")
            return None

        adaylar = []
        for t in tickers:
            symbol = t.get("symbol", "")

            if not symbol.endswith("USDT"):
                continue
            if symbol in mevcut_semboller:
                continue
            # Kaldıraçlı tokenları atla
            base = symbol.replace("USDT", "")
            if any(x in base for x in ["UP", "DOWN", "BULL", "BEAR"]):
                continue

            try:
                degisim = float(t["priceChangePercent"])
                hacim   = float(t["quoteVolume"])
                fiyat   = float(t["lastPrice"])
            except (KeyError, ValueError):
                continue

            if degisim <= DUSUS_ESIGI and hacim >= MIN_HACIM:
                rsi, oynaklik = teknik_analiz_yap(symbol)
                if rsi is not None and rsi < RSI_ESIGI and oynaklik is not None and oynaklik < OYNAKLIK_ESIGI:
                    adaylar.append({
                        "symbol":   symbol,
                        "price":    fiyat,
                        "rsi":      rsi,
                        "degisim":  degisim,
                        "oynaklik": oynaklik
                    })

        print(f"🔍 Tarama tamamlandı: {len(adaylar)} aday bulundu.")

        if not adaylar:
            return None

        # En düşük RSI = en aşırı satım → en iyi fırsat
        return sorted(adaylar, key=lambda x: x["rsi"])[0]

    except Exception as e:
        print(f"[FIRSAT_BUL HATA] {e}")
        return None

# ============================================================
# ANA DÖNGÜ
# ============================================================
def trading_loop():
    pozisyonlar = {}  # {symbol: {giris, en_yuksek, zaman, step_size, min_qty}}

    telegram_gonder(
        "⚡ <b>Bot Başlatıldı</b>\n"
        f"Kriter: %{abs(DUSUS_ESIGI)} Düşüş | RSI &lt;{RSI_ESIGI} | Stop %{STOP_LOSS_PCT}\n"
        f"Max Pozisyon: {MAX_POZISYON} | Bütçe/işlem: {ALIM_USDT} USDT"
    )

    while True:
        try:
            # --- YENİ POZİSYON AÇ ---
            if len(pozisyonlar) < MAX_POZISYON:
                firsat = firsat_bul(list(pozisyonlar.keys()))

                if firsat:
                    symbol = firsat["symbol"]
                    print(f"[ALIM DENEMESİ] {symbol} | RSI: {firsat['rsi']} | Değişim: {firsat['degisim']}%")

                    res = binance_istek("POST", "/api/v3/order", {
                        "symbol":        symbol,
                        "side":          "BUY",
                        "type":          "MARKET",
                        "quoteOrderQty": ALIM_USDT
                    })

                    if "orderId" in res and res.get("fills"):
                        giris_fiyat = float(res["fills"][0]["price"])
                        lot = sembol_bilgisi_al(symbol)
                        pozisyonlar[symbol] = {
                            "giris":     giris_fiyat,
                            "en_yuksek": giris_fiyat,
                            "zaman":     time.time(),
                            "step_size": lot["stepSize"],
                            "min_qty":   lot["minQty"]
                        }
                        telegram_gonder(
                            f"🚀 <b>ALIM: {symbol}</b>\n"
                            f"Fiyat: {giris_fiyat:.6f} USDT\n"
                            f"RSI: {firsat['rsi']} | Değişim: {firsat['degisim']:.2f}%\n"
                            f"Oynaklık: {firsat['oynaklik']:.2f}%"
                        )
                    else:
                        print(f"[ALIM BAŞARISIZ] {symbol}: {res}")

            # --- MEVCUT POZİSYONLARI KONTROL ET ---
            for symbol in list(pozisyonlar.keys()):
                try:
                    ticker_r = requests.get(
                        f"{BASE_URL}/api/v3/ticker/price",
                        params={"symbol": symbol},
                        timeout=10
                    ).json()
                    su_an = float(ticker_r["price"])
                except Exception as e:
                    print(f"[FİYAT HATA] {symbol}: {e}")
                    continue

                data = pozisyonlar[symbol]

                # İz süren en yüksek güncelle
                if su_an > data["en_yuksek"]:
                    pozisyonlar[symbol]["en_yuksek"] = su_an

                guncel_stop = pozisyonlar[symbol]["en_yuksek"] * (1 - STOP_LOSS_PCT / 100)
                gecen_sure  = time.time() - data["zaman"]

                stop_tetiklendi = su_an <= guncel_stop
                sure_doldu      = gecen_sure >= ZAMAN_LIMITI

                if stop_tetiklendi or sure_doldu:
                    neden = "⏱ SÜRE DOLDU" if sure_doldu else "🛑 STOP-LOSS"
                    asset = symbol.replace("USDT", "")
                    miktar_ham = serbest_miktar_al(asset)

                    if miktar_ham <= 0:
                        print(f"[SATIŞ HATA] {symbol}: Serbest bakiye 0 veya alınamadı.")
                        del pozisyonlar[symbol]
                        continue

                    miktar = miktari_formatla(miktar_ham, data["step_size"])

                    if miktar < data["min_qty"]:
                        print(f"[SATIŞ HATA] {symbol}: Miktar ({miktar}) min_qty ({data['min_qty']}) altında.")
                        del pozisyonlar[symbol]
                        continue

                    res = binance_istek("POST", "/api/v3/order", {
                        "symbol":   symbol,
                        "side":     "SELL",
                        "type":     "MARKET",
                        "quantity": miktar
                    })

                    if "orderId" in res:
                        kar_yuzde = ((su_an - data["giris"]) / data["giris"]) * 100
                        emoji = "✅" if kar_yuzde >= 0 else "❌"
                        telegram_gonder(
                            f"{emoji} <b>SATIŞ: {symbol}</b> [{neden}]\n"
                            f"Giriş: {data['giris']:.6f} | Çıkış: {su_an:.6f}\n"
                            f"Kâr/Zarar: %{kar_yuzde:.2f}"
                        )
                        del pozisyonlar[symbol]
                    else:
                        print(f"[SATIŞ BAŞARISIZ] {symbol}: {res}")

            print(f"[DURUM] Açık pozisyon: {len(pozisyonlar)}/{MAX_POZISYON} | {list(pozisyonlar.keys())}")
            time.sleep(TARAMA_ARALIK)

        except Exception as e:
            print(f"[ANA DÖNGÜ HATA] {e}")
            time.sleep(10)

# ============================================================
# BAŞLATMA — Thread __main__ dışında başlatılıyor (Render fix)
# ============================================================
t = Thread(target=trading_loop, daemon=True)
t.start()

if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("❌ HATA: BINANCE_API_KEY veya BINANCE_API_SECRET eksik!")
    else:
        print("✅ API anahtarları yüklendi.")

    if not TG_TOKEN:
        print("⚠️  Telegram token bulunamadı. Mesajlar yalnızca konsola yazılacak.")

    run_flask()
