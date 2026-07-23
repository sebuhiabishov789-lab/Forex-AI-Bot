"""
status_check.py v2.0 — "indi" əmri üçün polling
"""
import requests, os, csv, logging
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
import market_utils
import economic_calendar

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
OFFSET_FILE = Path("telegram_offset.txt")
TRIGGER_WORD = "A"
LOG_FILE = Path("signals_log.csv")

def get_saved_offset():
    if OFFSET_FILE.is_file():
        try:
            content = OFFSET_FILE.read_text().strip()
            if content.isdigit(): return int(content)
        except: pass
    return 0

def save_offset(uid):
    try: OFFSET_FILE.write_text(str(uid))
    except Exception as e: logger.error(f"Offset yazı xətası: {e}")

def get_updates(offset):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 0, "offset": offset}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("result", [])

def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for parse in ["Markdown", ""]:
        try:
            payload = {"chat_id": chat_id, "text": message, "parse_mode": parse} if parse else {"chat_id": chat_id, "text": message}
            resp = requests.post(url, json=payload, timeout=15)
            if resp.ok: return True
        except Exception as e:
            logger.error(f"Telegram xətası: {e}")
    return False

def get_market_session():
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 16: return "🇪🇺 London"
    if 13 <= h < 21: return "🇺🇸 NY"
    if 0 <= h < 9: return "🇯🇵 Asiya"
    return "🌐 Qarışıq"

def get_recent_performance():
    if not LOG_FILE.is_file(): return None
    try:
        with LOG_FILE.open('r', encoding='utf-8') as f:
            rows = [r for r in csv.DictReader(f) if r.get('outcome') and r['outcome']!='OPEN']
        if not rows: return None
        recent = rows[-5:]
        wins = sum(1 for r in recent if r['outcome']=='WIN')
        pips = sum(float(r['pip_result']) for r in recent if r.get('pip_result'))
        return f"Son {len(recent)}: {wins}✅ / {len(recent)-wins}❌ | {pips:+.1f} pip"
    except: return None

def build_status_message():
    status = market_utils.get_current_status()
    if not status: return "⚠ Data yoxdur, bir az sonra yoxla."

    prob, test_acc = status['prob'], status['test_acc']
    price, atr = status['current_price'], status['current_atr']
    
    slope = status['trend_slope']
    if slope > 0.0001: slope_desc = "kəskin yuxarı ⬆"
    elif slope > 0: slope_desc = "zəif yuxarı ↗"
    elif slope < -0.0001: slope_desc = "kəskin aşağı ⬇"
    elif slope < 0: slope_desc = "zəif aşağı ↘"
    else: slope_desc = "üfüqi ➖"

    agreement = "✅ Razı" if status['model_agreement']==1.0 else f"⚠ Fərqli RF:{status['rf_prob']:.0%} GB:{status['gb_prob']:.0%}"
    is_blackout, title, etime = economic_calendar.check_news_blackout()
    blackout_note = f"\n⚠ BLACKOUT: {title}\n" if is_blackout else ""
    perf = get_recent_performance()
    
    msg = (
        f"📍 *Bazar Statusu* {get_market_session()} {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
        f"━━━━━━━━━━━━\n"
        f"💵 {price:.5f} | ATR: {atr:.5f}\n"
        f"🔹 Trend: {'🟢 UP' if status['trend_up'] else '🔴 DOWN'} ({slope_desc})\n"
        f"📐 Fiqur: {status['pattern']}\n"
        f"🟢 Dəstək: {status['support']:.5f}\n" if status['support'] else "" +
        f"🔴 Direnc: {status['resistance']:.5f}\n" if status['resistance'] else "" +
        f"\n🧠 RF: {status['rf_prob']:.0%} | GB: {status['gb_prob']:.0%} | Ens: {prob:.0%} | Acc: {test_acc:.0%}\n"
        f"🤝 {agreement}\n"
        f"📊 BUY:{status['aligned_tf_up']}/5 SELL:{status['aligned_tf_down']}/5\n"
        f"{blackout_note}"
        f"{'📊 '+perf+'\n' if perf else ''}\n"
        f"📋 MTF:\n{market_utils.format_trends_block(status['mtf_trends'])}\n\n"
        f"📰 {economic_calendar.format_upcoming_high_impact(12)}"
    )
    return msg

def run():
    if not TOKEN or not CHAT_ID:
        logger.error("TOKEN/CHAT_ID yoxdur")
        return
    offset = get_saved_offset()
    try:
        updates = get_updates(offset)
    except Exception as e:
        logger.error(f"getUpdates: {e}")
        return
    if not updates:
        logger.info("Yeni mesaj yoxdur")
        save_offset(offset)
        return
    max_id = offset
    for upd in updates:
        uid = upd.get("update_id",0)
        max_id = max(max_id, uid+1)
        msg = upd.get("message")
        if not msg: continue
        text = msg.get("text","").strip().lower()
        cid = str(msg.get("chat",{}).get("id",""))
        if cid != str(CHAT_ID): continue
        if text == TRIGGER_WORD:
            logger.info("'indi' gəldi")
            send_telegram(cid, build_status_message())
    save_offset(max_id)

if __name__ == "__main__":
    run()
