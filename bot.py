import requests
import os
import csv
import json
from datetime import datetime, timezone, timedelta
import market_utils
import economic_calendar

LOG_FILE = "signals_log.csv"
STATE_FILE = "daily_signal_state.json"

# GitHub Secrets-dən məlumatları alır
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# --- Keyfiyyət tənzimləmələri ---
MIN_TEST_ACC = float(os.environ.get('MIN_TEST_ACC', 0.58))
BUY_THRESHOLD = 0.66
SELL_THRESHOLD = 0.34
REQUIRE_TECHNICAL_CONFIRMATION = True

# --- Gündəlik limit tənzimləmələri ---
MAX_SIGNALS_PER_DAY = 5
MIN_SIGNAL_GAP_HOURS = 2
MIN_CONFIDENCE_BASE = float(os.environ.get('MIN_CONFIDENCE', 0.60))

# --- Risk və lot hesablanması üçün parametrlər ---
ACCOUNT_BALANCE = float(os.environ.get('ACCOUNT_BALANCE', 1000))
RISK_PERCENT = float(os.environ.get('RISK_PERCENT', 1.0))
PIP_VALUE = float(os.environ.get('PIP_VALUE', 0.0001))
LOT_PIP_VALUE = float(os.environ.get('LOT_PIP_VALUE', 10.0))

# --- Volatillik filtri ---
MIN_ATR_RATIO = 0.6


def send_telegram(message):
    if TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        try:
            resp = requests.post(url, data=payload, timeout=15)
            if resp.status_code != 200:
                print(f"Telegram cavabı uğursuz: {resp.status_code} - {resp.text}")
        except requests.RequestException as e:
            print(f"Telegram xətası: {e}")
    else:
        print("TOKEN/CHAT_ID tapılmadı, mesaj göndərilmədi.")


def get_next_signal_id():
    max_id = 0
    if os.path.isfile(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get('signal_id', '')
                if sid and sid.isdigit():
                    max_id = max(max_id, int(sid))
    return max_id + 1


def log_signal(direction, entry, sl, tp, prob, test_acc, confidence, lot_size=None, signal_id=None):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'signal_id', 'timestamp_utc', 'direction', 'entry', 'sl', 'tp',
                'probability', 'model_test_acc', 'confidence',
                'lot_size', 'outcome', 'closed_at', 'pip_result'
            ])
        writer.writerow([
            signal_id if signal_id else '',
            datetime.now(timezone.utc).isoformat(), direction,
            round(entry, 5), round(sl, 5), round(tp, 5),
            round(prob, 4), round(test_acc, 4), round(confidence, 4),
            round(lot_size, 2) if lot_size else '',
            'OPEN', '', '',
        ])


def calculate_lot_size(entry, sl):
    risk_amount = ACCOUNT_BALANCE * (RISK_PERCENT / 100.0)
    sl_distance_pips = abs(entry - sl) / PIP_VALUE
    if sl_distance_pips == 0:
        return 0.0
    lot = risk_amount / (sl_distance_pips * LOT_PIP_VALUE)
    return max(round(lot, 2), 0.01)


def compute_confidence(prob, test_acc, tech_reasons_count, aligned_timeframes, model_agreement=1.0):
    direction_strength = abs(prob - 0.5) * 2
    tech_score = min(tech_reasons_count / 3, 1.0)
    acc_score = min(max((test_acc - 0.50) / 0.15, 0), 1)
    tf_score = min(aligned_timeframes / 5, 1.0)
    model_agree_score = model_agreement
    confidence = (
        0.35 * direction_strength +
        0.20 * tech_score +
        0.15 * acc_score +
        0.15 * tf_score +
        0.15 * model_agree_score
    )
    return round(confidence, 4)


def load_daily_state():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if state.get('date') == today:
                return today, state.get('count', 0), state.get('last_signal_at')
        except (json.JSONDecodeError, OSError):
            pass
    return today, 0, None


def save_daily_state(today, count, last_signal_at):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'date': today, 'count': count, 'last_signal_at': last_signal_at}, f)


def cooldown_active(last_signal_at):
    if not last_signal_at:
        return False
    try:
        last_dt = datetime.fromisoformat(last_signal_at)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - last_dt < timedelta(hours=MIN_SIGNAL_GAP_HOURS)


def get_recent_win_rate(last_n=10):
    if not os.path.isfile(LOG_FILE):
        return 0.5
    results = []
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            outcome = row.get('outcome', '').upper()
            if outcome in ('WIN', 'LOSS'):
                results.append(outcome)
    if not results:
        return 0.5
    recent = results[-last_n:]
    wins = recent.count('WIN')
    return wins / len(recent) if recent else 0.5


def dynamic_min_confidence():
    win_rate = get_recent_win_rate(10)
    if win_rate < 0.4:
        return MIN_CONFIDENCE_BASE + 0.15
    elif win_rate < 0.5:
        return MIN_CONFIDENCE_BASE + 0.08
    elif win_rate > 0.6:
        return max(0.55, MIN_CONFIDENCE_BASE - 0.05)
    else:
        return MIN_CONFIDENCE_BASE


def is_low_volatility(status):
    try:
        atr_ratio = status['data']['ATR_ratio'].iloc[-1]
        return atr_ratio < MIN_ATR_RATIO
    except (KeyError, IndexError):
        return False


def technical_confirms_buy(pattern, support, current_price, trend_slope):
    reasons = []
    if pattern in ("Double Bottom", "Triangle (converging)"):
        reasons.append(f"fiqur: {pattern}")
    if support is not None and (current_price - support) / current_price < 0.003:
        reasons.append("dəstək səviyyəsinə yaxın")
    if trend_slope > 0:
        reasons.append("trend xətti yuxarı meyllidir")
    return reasons


def technical_confirms_sell(pattern, resistance, current_price, trend_slope):
    reasons = []
    if pattern in ("Double Top", "Triangle (converging)"):
        reasons.append(f"fiqur: {pattern}")
    if resistance is not None and (resistance - current_price) / current_price < 0.003:
        reasons.append("müqavimət səviyyəsinə yaxın")
    if trend_slope < 0:
        reasons.append("trend xətti aşağı meyllidir")
    return reasons


def run_bot():
    status = market_utils.get_current_status()
    if status is None:
        print("Kifayət qədər data yoxdur, bot dayandırılır.")
        return

    prob = status['prob']
    test_acc = status['test_acc']
    current_price = status['current_price']
    current_atr = status['current_atr']
    trend_up = status['trend_up']
    trend_slope = status['trend_slope']
    support = status['support']
    resistance = status['resistance']
    pattern = status['pattern']
    aligned_tf_up = status['aligned_tf_up']
    aligned_tf_down = status['aligned_tf_down']
    model_agreement = status['model_agreement']
    trends_block = market_utils.format_trends_block(status['mtf_trends'])

    print(f"Model dəqiqliyi (TimeSeriesSplit): {test_acc:.2%}")

    if test_acc < MIN_TEST_ACC:
        print(f"Model dəqiqliyi kifayət qədər deyil ({test_acc:.2%}), siqnal göndərilmir.")
        return

    if is_low_volatility(status):
        print("ATR nisbəti çox aşağıdır (diapazon bazarı), siqnal göndərilmir.")
        return

    is_blackout, event_title, event_time = economic_calendar.check_news_blackout()
    if is_blackout:
        print(
            f"Yüksək təsirli xəbər aşkarlandı: '{event_title}' "
            f"({event_time.strftime('%H:%M UTC') if event_time else '?'}) — "
            f"siqnal göndərilmir (xəbər sükutu aktivdir)."
        )
        return

    today, sent_today, last_signal_at = load_daily_state()

    if sent_today >= MAX_SIGNALS_PER_DAY:
        print(f"Bugün üçün siqnal limiti dolub ({sent_today}/{MAX_SIGNALS_PER_DAY}), göndərilmir.")
        return

    if cooldown_active(last_signal_at):
        print(f"Son siqnaldan bəri {MIN_SIGNAL_GAP_HOURS} saat keçməyib, göndərilmir.")
        return

    dynamic_min_conf = dynamic_min_confidence()
    print(f"Dinamik minimum əminlik: {dynamic_min_conf:.2f} (baza: {MIN_CONFIDENCE_BASE})")

    signal_sent = False

    # ------------------------------------------------------------------ ALIŞ
    if prob > BUY_THRESHOLD and trend_up:
        tech_reasons = technical_confirms_buy(pattern, support, current_price, trend_slope)

        if REQUIRE_TECHNICAL_CONFIRMATION and not tech_reasons:
            print("ML ALIŞ siqnalı var, amma texniki təsdiq yoxdur — siqnal ötürüldü.")
        else:
            confidence = compute_confidence(prob, test_acc, len(tech_reasons), aligned_tf_up, model_agreement)

            if confidence < dynamic_min_conf:
                print(f"ALIŞ namizədi var, amma əminlik kifayət deyil ({confidence:.2f} < {dynamic_min_conf:.2f}), göndərilmir.")
            else:
                sl = support if support is not None else current_price - 1.5 * current_atr
                sl = max(sl, current_price - 0.5 * current_atr)
                tp = resistance if resistance is not None else current_price + 3.0 * current_atr
                tp = max(tp, current_price + 1.0 * current_atr)

                lot_size = calculate_lot_size(current_price, sl)
                signal_id = get_next_signal_id()

                reasons_str = ", ".join(tech_reasons) if tech_reasons else "yoxdur"

                msg = (
                    f"🚀 ALIŞ SİQNALI #{signal_id}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Giriş qiyməti: {current_price:.5f}\n"
                    f"🛑 Stop Loss: {sl:.5f}\n"
                    f"🎯 Take Profit: {tp:.5f}\n"
                    f"📊 Həcm: {lot_size} lot (hesabın {RISK_PERCENT}% riski)\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🤖 Model ehtimalı: {prob:.0%}\n"
                    f"📈 Model dəqiqliyi: {test_acc:.0%}\n"
                    f"🔹 RF: {status['rf_prob']:.0%} | GB: {status['gb_prob']:.0%}\n"
                    f"🎯 Əminlik: {confidence:.0%} (min. tələb: {dynamic_min_conf:.0%})\n"
                    f"📐 Fiqur: {pattern}\n"
                    f"✅ Texniki təsdiq: {reasons_str}\n"
                    f"📅 Bugünkü siqnal: {sent_today + 1}/{MAX_SIGNALS_PER_DAY}\n\n"
                    f"{trends_block}"
                )
                send_telegram(msg)
                log_signal('BUY', current_price, sl, tp, prob, test_acc, confidence, lot_size, signal_id)
                save_daily_state(today, sent_today + 1, datetime.now(timezone.utc).isoformat())
                signal_sent = True

    # ----------------------------------------------------------------- SATIŞ
    elif prob < SELL_THRESHOLD and not trend_up:
        tech_reasons = technical_confirms_sell(pattern, resistance, current_price, trend_slope)

        if REQUIRE_TECHNICAL_CONFIRMATION and not tech_reasons:
            print("ML SATIŞ siqnalı var, amma texniki təsdiq yoxdur — siqnal ötürüldü.")
        else:
            confidence = compute_confidence(1 - prob, test_acc, len(tech_reasons), aligned_tf_down, model_agreement)

            if confidence < dynamic_min_conf:
                print(f"SATIŞ namizədi var, amma əminlik kifayət deyil ({confidence:.2f} < {dynamic_min_conf:.2f}), göndərilmir.")
            else:
                sl = resistance if resistance is not None else current_price + 1.5 * current_atr
                sl = max(sl, current_price + 0.5 * current_atr)
                tp = support if support is not None else current_price - 3.0 * current_atr
                tp = min(tp, current_price - 1.0 * current_atr)

                lot_size = calculate_lot_size(current_price, sl)
                signal_id = get_next_signal_id()

                reasons_str = ", ".join(tech_reasons) if tech_reasons else "yoxdur"

                msg = (
                    f"📉 SATIŞ SİQNALI #{signal_id}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Giriş qiyməti: {current_price:.5f}\n"
                    f"🛑 Stop Loss: {sl:.5f}\n"
                    f"🎯 Take Profit: {tp:.5f}\n"
                    f"📊 Həcm: {lot_size} lot (hesabın {RISK_PERCENT}% riski)\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🤖 Model ehtimalı: {1 - prob:.0%}\n"
                    f"📈 Model dəqiqliyi: {test_acc:.0%}\n"
                    f"🔹 RF: {1 - status['rf_prob']:.0%} | GB: {1 - status['gb_prob']:.0%}\n"
                    f"🎯 Əminlik: {confidence:.0%} (min. tələb: {dynamic_min_conf:.0%})\n"
                    f"📐 Fiqur: {pattern}\n"
                    f"✅ Texniki təsdiq: {reasons_str}\n"
                    f"📅 Bugünkü siqnal: {sent_today + 1}/{MAX_SIGNALS_PER_DAY}\n\n"
                    f"{trends_block}"
                )
                send_telegram(msg)
                log_signal('SELL', current_price, sl, tp, 1 - prob, test_acc, confidence, lot_size, signal_id)
                save_daily_state(today, sent_today + 1, datetime.now(timezone.utc).isoformat())
                signal_sent = True

    if not signal_sent:
        print(
            f"Siqnal göndərilmədi. prob={prob:.2f}, trend_up={trend_up}, "
            f"test_acc={test_acc:.2%}, pattern={pattern}, bugün={sent_today}/{MAX_SIGNALS_PER_DAY}"
        )


if __name__ == "__main__":
    run_bot()
