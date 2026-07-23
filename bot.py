import os, csv, json, logging, requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import market_utils
import economic_calendar

# --- Konfiqurasiya ---
LOG_FILE = Path("signals_log.csv")
STATE_FILE = Path("daily_signal_state.json")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class Config:
    TOKEN = os.environ.get('TELEGRAM_TOKEN')
    CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
    MIN_TEST_ACC = float(os.environ.get('MIN_TEST_ACC', 0.58))
    BUY_THRESHOLD = 0.66
    SELL_THRESHOLD = 0.34
    MAX_SIGNALS_PER_DAY = 5
    MIN_SIGNAL_GAP_HOURS = 2
    MIN_CONFIDENCE_BASE = float(os.environ.get('MIN_CONFIDENCE', 0.60))
    ACCOUNT_BALANCE = float(os.environ.get('ACCOUNT_BALANCE', 1000))
    RISK_PERCENT = float(os.environ.get('RISK_PERCENT', 1.0))
    PIP_VALUE = 0.0001
    LOT_PIP_VALUE = 10.0
    MIN_ATR_RATIO = 0.6
    REQUIRE_TECHNICAL = True

config = Config()

def send_telegram(message: str, retries=2):
    if not (config.TOKEN and config.CHAT_ID):
        logger.warning("TOKEN/CHAT_ID yoxdur")
        return
    url = f"https://api.telegram.org/bot{config.TOKEN}/sendMessage"
    payload = {"chat_id": config.CHAT_ID, "text": message, "parse_mode": "HTML"}
    for i in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.ok: return
            logger.error(f"Telegram fail {r.status_code}: {r.text}")
        except requests.RequestException as e:
            logger.error(f"Telegram xəta (cehd {i+1}): {e}")
    logger.error("Telegram göndərilmədi")

def get_next_signal_id() -> int:
    if not LOG_FILE.exists(): return 1
    try:
        with LOG_FILE.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            ids = [int(r['signal_id']) for r in reader if r.get('signal_id','').isdigit()]
            return max(ids, default=0) + 1
    except Exception: return 1

def log_signal(direction, entry, sl, tp, prob, test_acc, confidence, lot_size=None, signal_id=None):
    is_new = not LOG_FILE.exists()
    try:
        with LOG_FILE.open('a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(['signal_id','timestamp_utc','direction','entry','sl','tp','probability','model_test_acc','confidence','lot_size','outcome','closed_at','pip_result'])
            w.writerow([signal_id, datetime.now(timezone.utc).isoformat(), direction, round(entry,5), round(sl,5), round(tp,5), round(prob,4), round(test_acc,4), round(confidence,4), round(lot_size,2) if lot_size else '', 'OPEN','',''])
    except OSError as e:
        logger.error(f"Log yazı xətası: {e}")

def calculate_lot_size(entry: float, sl: float) -> float:
    risk = config.ACCOUNT_BALANCE * (config.RISK_PERCENT / 100.0)
    pip_dist = abs(entry - sl) / config.PIP_VALUE
    if pip_dist < 1: return 0.01
    lot = risk / (pip_dist * config.LOT_PIP_VALUE)
    return max(round(lot, 2), 0.01)

def compute_confidence(prob, test_acc, tech_count, aligned_tf, model_agreement=1.0) -> float:
    return round(
        0.35 * abs(prob - 0.5) * 2 +
        0.20 * min(tech_count / 3, 1.0) +
        0.15 * min(max((test_acc - 0.5)/0.15, 0), 1) +
        0.15 * min(aligned_tf / 5, 1.0) +
        0.15 * model_agreement, 4
    )

def load_daily_state() -> Tuple[str, int, Optional[str]]:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text('utf-8'))
            if state.get('date') == today:
                return today, state.get('count',0), state.get('last_signal_at')
        except
