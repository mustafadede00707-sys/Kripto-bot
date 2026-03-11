import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

TELEGRAM_TOKEN = "8773224473:AAHGRlakz16tN4vFAbo-nEMylr3BhrCYmBU"
BINANCE_API_KEY = "XMiQx4boaVAYPQ6w7KRIQz1pwyTAiaw0TVIf2a11KojLFNMnfjzCpRvKD0onXOnc"
BINANCE_SECRET = "UioxraklkGh8lwFUmqkYMh8j5s10ldEtEamThXaqwm6q9lMiGh1aGUeKKqhk1yu7"

STOP_LOSS_PCT = 1.5
TAKE_PROFIT_PCT = 2.5
TRAILING_STEP = 0.5
CHECK_INTERVAL = 10
BINANCE_URL = "https://api.binance.com"

bot_state = {"aktif": False, "symbol": None, "giris_fiyat": None, "stop_loss": None, "take_profit": None, "chat_id": None, "mod": "bildirim", "islem_sayisi": 0}

def telegram_gonder(chat_id, mesaj):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": mesaj, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

def telegram_guncelle_al():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 5, "offset": telegram_guncelle_al.offset}, timeout=10)
        updates = r.json().get("result", [])
        if updates:
            telegram_guncelle_al.offset = updates[-1]["update_id"] + 1
        return updates
    except:
        return []

telegram_guncelle_al.offset = 0

def binance_imza(params):
    query = urlencode(params)
    return hmac.new(BINANCE_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def fiyat_al(symbol):
    try:
        r = requests.get(f"{BINANCE_URL}/api/v3/ticker/price", params={"symbol": symbol}, timeout=5)
        return float(r.json()["price"])
    except:
        return None

def komut_isle(chat_id, mesaj):
    global STOP_LOSS_PCT, TAKE_PROFIT_PCT
    parcalar = mesaj.strip().split()
    komut = parcalar[0].lower()
    if komut == "/baslat":
        bot_state["chat_id"] = chat_id
        telegram_gonder(chat_id, f"🤖 <b>Kripto Bot Aktif!</b>\n\n/takip BTCUSDT - Takip başlat\n/dur - Durdur\n/mod bildirim veya otomatik\n/ayar stop 1.5\n/ayar hedef 2.5\n/durum - Durum göster\n/fiyat BTCUSDT\n\n🔴 Stop: %{STOP_LOSS_PCT} 🟢 Hedef: %{TAKE_PROFIT_PCT}")
    elif komut == "/takip":
        if len(parcalar) < 2:
            telegram_gonder(chat_id, "Kullanım: /takip BTCUSDT"); return
        symbol = parcalar[1].upper()
        fiyat = fiyat_al(symbol)
        if not fiyat:
            telegram_gonder(chat_id, f"❌ {symbol} bulunamadı."); return
        bot_state.update({"aktif": True, "symbol": symbol, "giris_fiyat": fiyat, "stop_loss": fiyat*(1-STOP_LOSS_PCT/100), "take_profit": fiyat*(1+TAKE_PROFIT_PCT/100), "chat_id": chat_id})
        telegram_gonder(chat_id, f"✅ <b>{symbol} takibi başladı!</b>\n💰 Fiyat: {fiyat:.4f}\n🔴 Stop: {bot_state['stop_loss']:.4f}\n🟢 Hedef: {bot_state['take_profit']:.4f}\n⚙️ Mod: {bot_state['mod']}")
    elif komut == "/dur":
        bot_state["aktif"] = False; telegram_gonder(chat_id, "⏹️ Durduruldu.")
    elif komut == "/mod":
        if len(parcalar) > 1 and parcalar[1] in ["bildirim","otomatik"]:
            bot_state["mod"] = parcalar[1]; telegram_gonder(chat_id, f"✅ Mod: {parcalar[1]}")
    elif komut == "/ayar":
        if len(parcalar) > 2:
            try:
                d = float(parcalar[2])
                if parcalar[1]=="stop": STOP_LOSS_PCT=d; telegram_gonder(chat_id, f"🔴 Stop: %{d}")
                elif parcalar[1]=="hedef": TAKE_PROFIT_PCT=d; telegram_gonder(chat_id, f"🟢 Hedef: %{d}")
            except: pass
    elif komut == "/durum":
        if not bot_state["aktif"]:
            telegram_gonder(chat_id, "⏹️ Aktif takip yok."); return
        fiyat = fiyat_al(bot_state["symbol"])
        degisim = (fiyat - bot_state["giris_fiyat"]) / bot_state["giris_fiyat"] * 100 if fiyat else 0
        telegram_gonder(chat_id, f"📊 {bot_state['symbol']}\n💰 Giriş: {bot_state['giris_fiyat']:.4f}\n📈 Şu an: {fiyat:.4f}\n{'🟢' if degisim>=0 else '🔴'} %{degisim:.2f}\n🔴 Stop: {bot_state['stop_loss']:.4f}\n🟢 Hedef: {bot_state['take_profit']:.4f}")
    elif komut == "/fiyat":
        if len(parcalar) > 1:
            f = fiyat_al(parcalar[1].upper())
            telegram_gonder(chat_id, f"💰 {parcalar[1].upper()}: {f:.6f}" if f else "❌ Bulunamadı.")

def fiyat_kontrol():
    if not bot_state["aktif"]: return
    fiyat = fiyat_al(bot_state["symbol"])
    if not fiyat: return
    chat_id = bot_state["chat_id"]
    degisim = (fiyat - bot_state["giris_fiyat"]) / bot_state["giris_fiyat"] * 100
    tetiklendi = False
    if fiyat <= bot_state["stop_loss"]:
        telegram_gonder(chat_id, f"🔴 <b>STOP LOSS!</b>\n{bot_state['symbol']} = {fiyat:.4f}\n📉 %{degisim:.2f}\n{'⚡ Şimdi SAT!' if bot_state['mod']=='bildirim' else '🤖 Otomatik satış yapılıyor...'}")
        tetiklendi = True
    elif fiyat >= bot_state["take_profit"]:
        telegram_gonder(chat_id, f"🟢 <b>TAKE PROFIT!</b>\n{bot_state['symbol']} = {fiyat:.4f}\n📈 %{degisim:.2f}\n{'⚡ Şimdi SAT!' if bot_state['mod']=='bildirim' else '🤖 Otomatik satış yapılıyor...'}")
        tetiklendi = True
    if tetiklendi:
        bot_state["islem_sayisi"] += 1
        bot_state["giris_fiyat"] = fiyat
        bot_state["stop_loss"] = fiyat * (1-(STOP_LOSS_PCT+TRAILING_STEP)/100)
        bot_state["take_profit"] = fiyat * (1+(TAKE_PROFIT_PCT+TRAILING_STEP)/100)
        telegram_gonder(chat_id, f"⬆️ Seviyeler güncellendi!\n🔴 Yeni Stop: {bot_state['stop_loss']:.4f}\n🟢 Yeni Hedef: {bot_state['take_profit']:.4f}")

def main():
    print("🤖 Bot başlatıldı! Telegram'da /baslat yaz.")
    son_kontrol = 0
    while True:
        for update in telegram_guncelle_al():
            m = update.get("message", {})
            cid = m.get("chat", {}).get("id")
            txt = m.get("text", "")
            if cid and txt: komut_isle(cid, txt)
        if time.time() - son_kontrol >= CHECK_INTERVAL:
            fiyat_kontrol(); son_kontrol = time.time()
        time.sleep(1)

if __name__ == "__main__":
    main()import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot aktif")
    def log_message(self, format, *args):
        pass

def start_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=start_server, daemon
