import os, requests
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
import market_utils

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
OFFSET_FILE = Path("telegram_offset.txt")
TRIGGER = "a"

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
    r = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=15).json()
    results = r.get("result", [])
    if not results:
        save_offset(offset)
        return
    max_id = offset
    for upd in results:
        uid = upd.get("update_id", 0)
        max_id = max(max_id, uid + 1)
        msg = upd.get("message")
        if not msg:
            continue
        text = str(msg.get("text", "")).lower().strip()
        cid = str(msg.get("chat", {}).get("id", ""))
        if cid != CHAT_ID:
            continue
        if text == TRIGGER:
            st = market_utils.get_current_status()
            if not st:
                txt = "Data yoxdur"
            else:
                txt = "Qiymet: " + str(st['current_price']) + "\nProb: " + str(st['prob']) + "\nTrend UP: " + str(st['trend_up'])
            requests.post("https://api.telegram.org/bot" + TOKEN + "/sendMessage", json={"chat_id": cid, "text": txt}, timeout=15)
    save_offset(max_id)

if __name__ == "__main__":
    run()
