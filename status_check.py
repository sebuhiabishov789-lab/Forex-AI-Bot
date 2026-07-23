import requests, os, csv, logging
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
import market_utils
import economic_calendar

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
OFFSET_FILE = Path("telegram_offset.txt")
TRIGGER_WORD = "a"
LOG_FILE = Path("signals_log.csv")

def get_saved_offset():
    if OFFSET_FILE.is_file():
        try:
            c = OFFSET_FILE.read_text().strip()
            if c.isdigit():
                return int(c)
        except:
            pass
    return 0

def save_offset(uid):
    try:
        OFFSET_FILE.write_text(str(uid))
    except Exception as e:
        logger.error(e)

def get_updates(offset):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 0, "offset": offset}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("result", [])

def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        payload = {"chat_id": chat_id, "text": message}
        resp = requests.post(url, json=payload, timeout=15)
        return resp.ok
    except Exception as e:
        logger.error(e)
        return False

def get_market_session():
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 16:
        return "EU London"
    if 13 <= h < 21:
        return "US NY"
    if 0 <= h < 9:
        return "JP Asiya"
    return "Qarisiq"

def build_status_message():
    status = market_utils.get_current_status()
    if not status:
        return "Data yoxdur"

    prob = status['prob']
    price = status['current_price']
    atr = status['current_atr']
    pattern = status['pattern']
    mtf = market_utils.format_trends_block(status['mtf_trends'])
    news = economic_calendar.format_upcoming_high_impact(12)
    session = get_market_session()
    now_str = datetime.now(timezone.utc).strftime('%H:%M UTC')
    
    support_val = status.get('support')
    resistance_val = status.get('resistance')
    
    if support_val is not None:
        support_txt = str(round(support_val, 5))
    else:
        support_txt = "-"
        
    if resistance_val is not None:
        resistance_txt = str(round(resistance_val, 5))
    else:
        resistance_txt = "-"

    if status['trend_up']:
        trend_txt = "UP"
    else:
        trend_txt = "DOWN"

    rf = status['rf_prob']
    gb = status['gb_prob']
    
    # mesajı hissə-hissə yığırıq, f-string içində \n yoxdur
    parts = []
    parts.append(f"Bazar Statusu {session} {now_str}")
    parts.append("----------------")
    parts.append(f"Qiymet: {price} ATR: {atr}")
    parts.append(f"Trend: {trend_txt} Pattern: {pattern}")
    parts.append(f"Destek: {support_txt} Direnc: {resistance_txt}")
    parts.append(f"RF: {rf} GB: {gb} ENS: {prob}")
    parts.append("")
    parts.append("MTF:")
    parts.append(mtf)
    parts.append("")
    parts.append(news)
    
    final_msg = "\n".join(parts)
    return final_msg

def run():
    if not TOKEN or not CHAT_ID:
        logger.error("TOKEN yoxdur")
        return
    offset = get_saved_offset()
    try:
        updates = get_updates(offset)
    except Exception as e:
        logger.error(e)
        return
    if not updates:
        logger.info("Yeni mesaj yoxdur")
        save_offset(offset)
        return
    max_id = offset
    for upd in updates:
        uid = upd.get("update_id", 0)
        if uid + 1 > max_id:
            max_id = uid + 1
        msg = upd.get("message")
        if not msg:
            continue
        text = msg.get("text", "").strip().lower()
        cid = str(msg.get("chat", {}).get("id", ""))
        if cid != str(CHAT_ID):
            continue
        if text == TRIGGER_WORD:
            logger.info("Trigger geldi")
            txt = build_status_message()
            send_telegram(cid, txt)
    save_offset(max_id)

if __name__ == "__main__":
    run()
