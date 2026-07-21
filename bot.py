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
MIN_TEST_ACC = 0.53
BUY_THRESHOLD = 0.66
SELL_THRESHOLD = 0.34

# True: yalnız ML siqnalı VƏ texniki analiz (fiqur/support-resistance/trend
# xətti) eyni istiqamətə işarə etdikdə siqnal namizədi kimi qəbul edilir.
REQUIRE_TECHNICAL_CONFIRMATION = True

# --- Gündəlik limit tənzimləmələri ---
MAX_SIGNALS_PER_DAY = 5
MIN_SIGNAL_GAP_HOURS = 2  # ard-arda siqnallar arasında minimum aralıq
MIN_CONFIDENCE = 0.60  # 0-1 aralığında, bundan aşağı əminlikli siqnal göndərilmir


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


def log_signal(direction, entry, sl, tp, prob, test_acc, confidence):
    """Hər göndərilən siqnalı CSV-ə yazır ki, zamanla real statistika toplansın."""
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'timestamp_utc', 'direction', 'entry', 'sl', 'tp',
                'probability', 'model_test_acc', 'confidence',
                'outcome', 'closed_at', 'pip_result'
            ])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(), direction,
            round(entry, 5), round(sl, 5), round(tp, 5),
            round(prob, 4), round(test_acc, 4), round(confidence, 4),
            'OPEN', '', '',
        ])


def compute_confidence(prob, test_acc, tech_reasons_count, aligned_timeframes):
    """
    ML ehtimalı, model dəqiqliyi, texniki təsdiq sayı və üst-üstə düşən
    zaman dilimi trendlərini birləşdirib 0-1 aralığında əminlik skoru verir.
    """
    direction_strength = abs(prob - 0.5) * 2  # 0..1, 0.5-dən nə qədər uzaqdır
    tech_score = min(tech_reasons_count / 3, 1.0)  # 0..1
    acc_score = min(max((test_acc - 0.50) / 0.15, 0), 1)  # 0.50-0.65 aralığını 0..1-ə xəritələyir
    tf_score = min(aligned_timeframes / 5, 1.0)  # 0..1, neçə TF eyni istiqamətdədir

    confidence = (
        0.40 * direction_strength +
        0.25 * tech_score +
        0.15 * acc_score +
        0.20 * tf_score
    )
    return round(confidence, 4)


def load_daily_state():
    """Bugünkü göndərilən siqnal sayını və son siqnalın vaxtını oxuyur."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if state.get('date') == today:
                return today, state.get('count', 0), state.get('last_signal_at')
        except (json.JSONDecodeError, OSError):
            pass
    # Fayl yoxdur, oxuna bilmir, ya da tarix dəyişib — sıfırdan başla
    return today, 0, None


def save_daily_state(today, count, last_signal_at):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'date': today, 'count': count, 'last_signal_at': last_signal_at}, f)


def cooldown_active(last_signal_at):
    """Son siqnaldan bəri minimum aralıq keçməyibsə True qaytarır."""
    if not last_signal_at:
        return False
    try:
        last_dt = datetime.fromisoformat(last_signal_at)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - last_dt < timedelta(hours=MIN_SIGNAL_GAP_HOURS)


def technical_confirms_buy(pattern, support, current_price, trend_slope):
    """BUY siqnalını texniki analizlə təsdiqləyir, təsdiq səbəblərini qaytarır."""
    reasons = []
    if pattern in ("Double Bottom", "Triangle (converging)"):
        reasons.append(f"fiqur: {pattern}")
    if support is not None and (current_price - support) / current_price < 0.003:
        reasons.append("support səviyyəsinə yaxın")
    if trend_slope > 0:
        reasons.append("trend xətti yuxarı meyllidir")
    return reasons


def technical_confirms_sell(pattern, resistance, current_price, trend_slope):
    """SELL siqnalını texniki analizlə təsdiqləyir, təsdiq səbəblərini qaytarır."""
    reasons = []
    if pattern in ("Double Top", "Triangle (converging)"):
        reasons.append(f"fiqur: {pattern}")
    if resistance is not None and (resistance - current_price) / current_price < 0.003:
        reasons.append("resistance səviyyəsinə yaxın")
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
    trends_block = market_utils.format_trends_block(status['mtf_trends'])

    print(f"Model dəqiqliyi (TimeSeriesSplit): {test_acc:.2%}")

    if test_acc < MIN_TEST_ACC:
        print(f"Model dəqiqliyi kifayət qədər deyil ({test_acc:.2%}), siqnal göndərilmir.")
        return

    # --- Fundamental analiz: yüksək təsirli xəbər sükutu ---
    is_blackout, event_title, event_time = economic_calendar.check_news_blackout()
    if is_blackout:
        print(
            f"Yüksək təsirli xəbər aşkarlandı: '{event_title}' "
            f"({event_time.strftime('%H:%M UTC') if event_time else '?'}) — "
            f"siqnal göndərilmir (xəbər sükutu aktivdir)."
        )
        return

    # --- Gündəlik limit və cooldown yoxlaması ---
    today, sent_today, last_signal_at = load_daily_state()

    if sent_today >= MAX_SIGNALS_PER_DAY:
        print(f"Bugün üçün siqnal limiti dolub ({sent_today}/{MAX_SIGNALS_PER_DAY}), göndərilmir.")
        return

    if cooldown_active(last_signal_at):
        print(f"Son siqnaldan bəri {MIN_SIGNAL_GAP_HOURS} saat keçməyib, göndərilmir.")
        return

    signal_sent = False

    # ------------------------------------------------------------------ BUY
    if prob > BUY_THRESHOLD and trend_up:
        tech_reasons = technical_confirms_buy(pattern, support, current_price, trend_slope)

        if REQUIRE_TECHNICAL_CONFIRMATION and not tech_reasons:
            print("ML BUY siqnalı var, amma texniki təsdiq yoxdur — siqnal ötürüldü.")
        else:
            confidence = compute_confidence(prob, test_acc, len(tech_reasons), aligned_tf_up)

            if confidence < MIN_CONFIDENCE:
                print(f"BUY namizədi var, amma əminlik kifayət deyil ({confidence:.2f} < {MIN_CONFIDENCE}), göndərilmir.")
            else:
                sl = support if support is not None else current_price - 1.5 * current_atr
                sl = min(sl, current_price - 0.5 * current_atr)
                tp = resistance if resistance is not None else current_price + 3.0 * current_atr
                tp = max(tp, current_price + 1.0 * current_atr)

                confidence_note = f"✅ Texniki təsdiq: {', '.join(tech_reasons)}"

                msg = (
                    f"🚀 SİQNAL: ALIŞ (BUY)\n"
                    f"Qiymət: {round(current_price, 5)}\n"
                    f"SL: {round(sl, 5)}\n"
                    f"TP: {round(tp, 5)}\n"
                    f"Ehtimal: {prob:.0%} | Model dəqiqliyi: {test_acc:.0%}\n"
                    f"Əminlik skoru: {confidence:.0%}\n"
                    f"Fiqur: {pattern}\n"
                    f"{confidence_note}\n"
                    f"Bugünkü siqnal: {sent_today + 1}/{MAX_SIGNALS_PER_DAY}\n\n"
                    f"{trends_block}"
                )
                send_telegram(msg)
                log_signal('BUY', current_price, sl, tp, prob, test_acc, confidence)
                save_daily_state(today, sent_today + 1, datetime.now(timezone.utc).isoformat())
                signal_sent = True

    # ----------------------------------------------------------------- SELL
    elif prob < SELL_THRESHOLD and not trend_up:
        tech_reasons = technical_confirms_sell(pattern, resistance, current_price, trend_slope)

        if REQUIRE_TECHNICAL_CONFIRMATION and not tech_reasons:
            print("ML SELL siqnalı var, amma texniki təsdiq yoxdur — siqnal ötürüldü.")
        else:
            confidence = compute_confidence(1 - prob, test_acc, len(tech_reasons), aligned_tf_down)

            if confidence < MIN_CONFIDENCE:
                print(f"SELL namizədi var, amma əminlik kifayət deyil ({confidence:.2f} < {MIN_CONFIDENCE}), göndərilmir.")
            else:
                sl = resistance if resistance is not None else current_price + 1.5 * current_atr
                sl = max(sl, current_price + 0.5 * current_atr)
                tp = support if support is not None else current_price - 3.0 * current_atr
                tp = min(tp, current_price - 1.0 * current_atr)

                confidence_note = f"✅ Texniki təsdiq: {', '.join(tech_reasons)}"

                msg = (
                    f"📉 SİQNAL: SATIŞ (SELL)\n"
                    f"Qiymət: {round(current_price, 5)}\n"
                    f"SL: {round(sl, 5)}\n"
                    f"TP: {round(tp, 5)}\n"
                    f"Ehtimal: {1 - prob:.0%} | Model dəqiqliyi: {test_acc:.0%}\n"
                    f"Əminlik skoru: {confidence:.0%}\n"
                    f"Fiqur: {pattern}\n"
                    f"{confidence_note}\n"
                    f"Bugünkü siqnal: {sent_today + 1}/{MAX_SIGNALS_PER_DAY}\n\n"
                    f"{trends_block}"
                )
                send_telegram(msg)
                log_signal('SELL', current_price, sl, tp, 1 - prob, test_acc, confidence)
                save_daily_state(today, sent_today + 1, datetime.now(timezone.utc).isoformat())
                signal_sent = True

    if not signal_sent:
        print(
            f"Siqnal göndərilmədi. prob={prob:.2f}, trend_up={trend_up}, "
            f"test_acc={test_acc:.2%}, pattern={pattern}, bugün={sent_today}/{MAX_SIGNALS_PER_DAY}"
        )


if __name__ == "__main__":
    run_bot()
