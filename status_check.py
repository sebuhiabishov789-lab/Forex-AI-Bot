import os, requests
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import market_utils

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
OFFSET_FILE = Path("telegram_offset.txt")
TRIGGER = "a"
NL = chr(10)

def get_offset():
    if OFFSET_FILE.exists():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except (ValueError, OSError) as e:
            print(f"Offset faylı oxunmadı, 0-dan başlanır: {e}")
            return 0
    return 0

def save_offset(v):
    OFFSET_FILE.write_text(str(v))

def run():
    offset = get_offset()
    url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates"
    r = requests.get(url, params={"offset": offset}, timeout=15).json()
    results = r.get("result", [])
    max_id = offset
    for upd in results:
        uid = upd.get("update_id", 0)
        if uid + 1 > max_id:
            max_id = uid + 1
        m = upd.get("message")
        if not m:
            continue
        txt_in = str(m.get("text","")).strip().lower()
        cid = str(m.get("chat",{}).get("id",""))
        if cid != CHAT_ID:
            continue
        if txt_in == TRIGGER:
            # Önce canlı dene, olmazsa cache'den al
            st = market_utils.get_current_status()
            if st is None:
                st = market_utils._load_last_status()
            
            if st is None:
                msg = "⚠️ Data yoxdur - bot yenilənir, 1 dəqiqə sonra yenidən A yaz"
            elif st.get("is_synthetic"):
                msg = "⚠️ Hazırda real bazar datası əlçatan deyil (yfinance/Frankfurter cavab vermir). Göstəriləcək rəqəmlər etibarlı olmazdı, ona görə bu dəfə göndərilmir - bir az sonra yenidən 'A' yaz."
            else:
                try:
                    price = float(st.get("current_price", 0))
                    prob = float(st.get("prob", 0))
                    trend_up = st.get("trend_up", False)
                    atr = float(st.get("current_atr", 0))
                    pattern = st.get("pattern", "")
                    
                    trend_txt = "Yuxarı 🟢" if trend_up else "Aşağı 🔴"
                    prob_pct = prob * 100
                    
                    if prob >= 0.66:
                        sig = "🟢 BUY siqnalına yaxın"
                    elif prob <= 0.34:
                        sig = "🔴 SELL siqnalına yaxın"
                    else:
                        sig = "⚪ Gözləmə"

                    msg = (
                        f"💰 EUR/USD: {price:.5f}" + NL +
                        f"{sig}" + NL +
                        f"📊 Prob: {prob_pct:.1f}%" + NL +
                        f"📈 Trend: {trend_txt}" + NL +
                        f"📏 ATR: {atr:.5f}" + NL +
                        f"🔍 Pattern: {pattern}"
                    )
                except Exception as e:
                    # Hata olursa eski basit format
                    p = str(st.get("current_price"))
                    pr = str(st.get("prob"))
                    up = str(st.get("trend_up"))
                    msg = "Qiymet: " + p + NL + "Prob: " + pr + NL + "Trend UP: " + up

            requests.post("https://api.telegram.org/bot" + TOKEN + "/sendMessage", json={"chat_id": cid, "text": msg}, timeout=15)
    save_offset(max_id)

if __name__ == "__main__":
    run()
