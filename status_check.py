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
        except:
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
            st = market_utils.get_current_status()
            if st is None:
                msg = "Data yoxdur"
            else:
                p = str(st.get("current_price"))
                pr = str(st.get("prob"))
                up = str(st.get("trend_up"))
                msg = "Qiymet: " + p + NL + "Prob: " + pr + NL + "Trend UP: " + up
            requests.post("https://api.telegram.org/bot" + TOKEN + "/sendMessage", json={"chat_id": cid, "text": msg}, timeout=15)
    save_offset(max_id)

if __name__ == "__main__":
    run()
