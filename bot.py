import os, csv, json, logging, requests, html
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

import market_utils
import economic_calendar

LOG_FILE = Path("signals_log.csv")
STATE_FILE = Path("daily_signal_state.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class Config:
    TOKEN = os.environ.get('TELEGRAM_TOKEN')
    CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
    MIN_TEST_ACC = float(os.environ.get('MIN_TEST_ACC', '0.50'))
    BUY_THRESHOLD = 0.58
    SELL_THRESHOLD = 0.42
    MAX_SIGNALS_PER_DAY = 5
    MIN_SIGNAL_GAP_HOURS = 2
    MIN_CONFIDENCE_BASE = float(os.environ.get('MIN_CONFIDENCE', '0.52'))
    ACCOUNT_BALANCE = float(os.environ.get('ACCOUNT_BALANCE', '1000'))
    RISK_PERCENT = float(os.environ.get('RISK_PERCENT', '1.0'))
    PIP_VALUE = 0.0001
    LOT_PIP_VALUE = 10.0
    MIN_ATR_RATIO = 0.4
    MAX_CONSECUTIVE_LOSSES = int(os.environ.get('MAX_CONSECUTIVE_LOSSES', '4'))
    LOSS_STREAK_COOLDOWN_HOURS = float(os.environ.get('LOSS_STREAK_COOLDOWN_HOURS', '12'))

config = Config()

def send_telegram(message: str, retries=2):
    if not (config.TOKEN and config.CHAT_ID):
        logger.warning("TOKEN/CHAT_ID yoxdur - .env yoxla")
        return False
    url = f"https://api.telegram.org/bot{config.TOKEN}/sendMessage"
    payload = {"chat_id": config.CHAT_ID, "text": message, "parse_mode": "HTML"}
    for i in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.ok: return True
            logger.error(f"Telegram {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"Telegram cehd {i+1}: {e}")
    return False

def get_next_signal_id() -> int:
    if not LOG_FILE.exists(): return 1
    try:
        with LOG_FILE.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            ids = [int(row['signal_id']) for row in reader if row.get('signal_id','').isdigit()]
            return max(ids, default=0) + 1
    except Exception as e:
        logger.warning(f"signal_id oxunmadı, 1-dən başlanır: {e}")
        return 1

def log_signal(direction, entry, sl, tp, prob, test_acc, confidence, lot_size=None, signal_id=None):
    is_new = not LOG_FILE.exists()
    try:
        with LOG_FILE.open('a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(['signal_id','timestamp_utc','direction','entry','sl','tp','probability','model_test_acc','confidence','lot_size','outcome','closed_at','pip_result'])
            w.writerow([signal_id, datetime.now(timezone.utc).isoformat(), direction, round(entry,5), round(sl,5), round(tp,5), round(prob,4), round(test_acc,4), round(confidence,4), round(lot_size,2) if lot_size else '', 'OPEN','',''])
    except Exception as e:
        logger.error(f"Log yazı xətası: {e}")

def calculate_lot_size(entry: float, sl: float) -> float:
    risk_amount = config.ACCOUNT_BALANCE * (config.RISK_PERCENT / 100.0)
    pip_dist = abs(entry - sl) / config.PIP_VALUE
    if pip_dist < 1: return 0.01
    lot = risk_amount / (pip_dist * config.LOT_PIP_VALUE)
    return max(round(lot, 2), 0.01)

def compute_confidence(prob, test_acc, tech_count, aligned_tf, model_agreement=1.0) -> float:
    return round(0.35*abs(prob-0.5)*2 + 0.20*min(tech_count/3,1.0) + 0.15*min(max((test_acc-0.5)/0.15,0),1) + 0.15*min(aligned_tf/5,1.0) + 0.15*model_agreement, 4)

def load_daily_state():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text('utf-8'))
            if state.get('date') == today:
                return today, state.get('count',0), state.get('last_signal_at')
        except Exception as e:
            logger.warning(f"Gündəlik state oxunmadı: {e}")
    return today, 0, None

def save_daily_state(date_str, count, last_at):
    try:
        STATE_FILE.write_text(json.dumps({'date': date_str, 'count': count, 'last_signal_at': last_at}), encoding='utf-8')
    except Exception as e:
        logger.error(f"State yazı xətası: {e}")

def can_send_signal(current_count, last_signal_at_str):
    if current_count >= config.MAX_SIGNALS_PER_DAY:
        return False, f"Günlük limit ({config.MAX_SIGNALS_PER_DAY}) dolub"
    if last_signal_at_str:
        try:
            last = datetime.fromisoformat(last_signal_at_str)
            if datetime.now(timezone.utc) - last < timedelta(hours=config.MIN_SIGNAL_GAP_HOURS):
                return False, f"Son siqnaldan {config.MIN_SIGNAL_GAP_HOURS} saat keçməyib"
        except Exception as e:
            logger.warning(f"Son siqnal vaxtı parse olunmadı: {e}")
    return True, "OK"

def check_loss_streak() -> Tuple[bool, str]:
    """Son bağlanmış (OPEN olmayan) siqnallara baxıb ardıcıl neçə LOSS olduğunu
    hesablayır. MAX_CONSECUTIVE_LOSSES-ə çatıbsa, son itkidən LOSS_STREAK_COOLDOWN_HOURS
    saat ərzində yeni siqnal göndərilməsinin qarşısını alır (circuit breaker)."""
    if not LOG_FILE.exists():
        return True, "OK"
    try:
        with LOG_FILE.open('r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        logger.warning(f"Loss-streak yoxlaması üçün log oxunmadı: {e}")
        return True, "OK"

    closed = [r for r in rows if r.get('outcome', '').upper() in ('WIN', 'LOSS')]
    if not closed:
        return True, "OK"
    closed.sort(key=lambda r: r.get('closed_at') or '', reverse=True)

    streak = 0
    last_loss_closed_at = None
    for r in closed:
        if r.get('outcome', '').upper() == 'LOSS':
            streak += 1
            if last_loss_closed_at is None:
                last_loss_closed_at = r.get('closed_at')
        else:
            break

    if streak >= config.MAX_CONSECUTIVE_LOSSES:
        try:
            closed_at = datetime.fromisoformat(last_loss_closed_at)
            if datetime.now(timezone.utc) - closed_at < timedelta(hours=config.LOSS_STREAK_COOLDOWN_HOURS):
                return False, f"{streak} ardıcıl itki - {config.LOSS_STREAK_COOLDOWN_HOURS} saatlıq soyuma dövründəyik"
        except Exception:
            # closed_at parse olunmadısa, ehtiyat tədbiri kimi yenə də dayandırırıq
            return False, f"{streak} ardıcıl itki - soyuma dövrü (vaxt oxunmadı)"

    return True, "OK"

def main():
    logger.info("=== Forex AI Bot başladı ===")
    status = market_utils.get_current_status()
    if not status:
        logger.error("Data alınmadı")
        return

    # === BURASI YENİ - TELEGRAM A İÇİN CACHE HER DURUMDA KAYDEDİLSİN ===
    try:
        market_utils._save_last_status(status)
        logger.info(f"last_status.json kaydedildi: {status.get('current_price')}")
    except Exception as e:
        logger.error(f"Cache kayıt hatası: {e}")

    if status.get('is_synthetic'):
        logger.error("Data SİNTETİKDİR (yfinance/Frankfurter uğursuz oldu) - siqnal göndərilmir, təhlükəsizlik dayanması")
        return

    prob = status['prob']
    test_acc = status['test_acc']
    price = status['current_price']
    atr = status['current_atr']

    # Xəbər filtri
    is_blackout, title, etime = economic_calendar.check_news_blackout()
    if is_blackout:
        logger.info(f"Xəbər blackout: {title} - siqnal dayandırıldı")
        return

    # ATR filtri
    hist_atr_median = status['data']['ATR'].rolling(50).median().iloc[-1]
    atr_ratio = atr / hist_atr_median if hist_atr_median else 1
    if atr_ratio < config.MIN_ATR_RATIO:
        logger.info(f"ATR çox aşağı ({atr_ratio:.2f}) - siqnal yoxdur")
        return

    if test_acc < config.MIN_TEST_ACC:
        logger.info(f"Model dəqiqliyi aşağı {test_acc:.2f} < {config.MIN_TEST_ACC}")
        return

    direction = None
    if prob >= config.BUY_THRESHOLD: direction = "BUY"
    elif prob <= config.SELL_THRESHOLD: direction = "SELL"
    
    if not direction:
        logger.info(f"Siqnal yoxdur prob={prob:.3f}")
        return

    # Texniki təsdiq
    tech_count = 0
    if status['trend_up'] and direction=="BUY": tech_count+=1
    if not status['trend_up'] and direction=="SELL": tech_count+=1
    if status['support'] and status['resistance']: tech_count+=1

    aligned = status['mtf_trends']
    aligned_count = sum(1 for v in aligned.values() if (direction=="BUY" and "Yuxarı" in v) or (direction=="SELL" and "Aşağı" in v))

    confidence = compute_confidence(prob, test_acc, tech_count, aligned_count, status['model_agreement'])

    if confidence < config.MIN_CONFIDENCE_BASE:
        logger.info(f"Confidence aşağı {confidence:.2f}")
        return

    # Gündəlik limit
    today, count, last_at = load_daily_state()
    can_send, reason = can_send_signal(count, last_at)
    if not can_send:
        logger.info(f"Göndərilmədi: {reason}")
        return

    # Ardıcıl itki circuit breaker
    streak_ok, streak_reason = check_loss_streak()
    if not streak_ok:
        logger.info(f"Göndərilmədi: {streak_reason}")
        return

    # SL/TP
    sl = price - atr*1.5 if direction=="BUY" else price + atr*1.5
    tp = price + atr*2.5 if direction=="BUY" else price - atr*2.5
    lot = calculate_lot_size(price, sl)
    signal_id = get_next_signal_id()

    msg = (
        f"{'🟢' if direction=='BUY' else '🔴'} <b>#{signal_id} {direction} SİQNALI - EUR/USD</b>\n"
        f"💰 Qiymət: {price:.5f}\n"
        f"📉 SL: {sl:.5f} | 📈 TP: {tp:.5f}\n"
        f"📊 Ehtimal: {prob*100:.1f}% | Dəqiqlik: {test_acc*100:.1f}%\n"
        f"🎯 Güvən: {confidence*100:.0f}% | Lot: {lot}\n"
        f"ATR nisbəti: {atr_ratio:.2f}\n"
        f"Pattern: {html.escape(str(status['pattern']))}\n"
        f"{html.escape(economic_calendar.format_upcoming_high_impact(12))}"
    )

    if send_telegram(msg):
        log_signal(direction, price, sl, tp, prob, test_acc, confidence, lot, signal_id)
        save_daily_state(today, count+1, datetime.now(timezone.utc).isoformat())
        logger.info(f"Siqnal #{signal_id} göndərildi")

if __name__ == "__main__":
    main()
