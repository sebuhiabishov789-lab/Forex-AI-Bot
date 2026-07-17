import requests
import os
import csv
from datetime import datetime
import market_utils

LOG_FILE = "signals_log.csv"

# GitHub Secrets-dən məlumatları alır
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# --- Tənzimləmələr ---
MIN_TEST_ACC = 0.52
BUY_THRESHOLD = 0.62
SELL_THRESHOLD = 0.38

# True olarsa: yalnız ML siqnalı VƏ texniki analiz (fiqur/support-resistance/
# trend xətti) eyni istiqamətə işarə etdikdə siqnal göndərilir.
# False olarsa: ML siqnalı kifayətdir, texniki təsdiq mesajda qeyd olunur amma bloklamır.
REQUIRE_TECHNICAL_CONFIRMATION = False


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


def log_signal(direction, entry, sl, tp, prob, test_acc):
    """Hər göndərilən siqnalı CSV-ə yazır ki, zamanla real statistika toplansın."""
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'timestamp_utc', 'direction', 'entry', 'sl', 'tp',
                'probability', 'model_test_acc', 'outcome', 'closed_at', 'pip_result'
            ])
        writer.writerow([
            datetime.utcnow().isoformat(), direction,
            round(entry, 5), round(sl, 5), round(tp, 5),
            round(prob, 4), round(test_acc, 4), 'OPEN', '', '',
        ])


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
    support = status['support']
    resistance = status['resistance']
    pattern = status['pattern']
    trend_slope = status['data']['Trend_slope'].iloc[-1]
    trends_block = market_utils.format_trends_block(status['mtf_trends'])

    print(f"Test dəqiqliyi (son 20% data üzərində): {test_acc:.2%}")

    # Yalnız modelin trendlə üst-üstə düşən proqnozlarına etibar edilir.
    # Model real test dəqiqliyi ən azı MIN_TEST_ACC-dən yüksək olmalıdır,
    # əks halda model hazırkı bazar şəraitində etibarsız sayılır və siqnal göndərilmir.
    if test_acc < MIN_TEST_ACC:
        print(f"Model dəqiqliyi kifayət qədər deyil ({test_acc:.2%}), siqnal göndərilmir.")
        return

    signal_sent = False

    # ------------------------------------------------------------------ BUY
    if prob > BUY_THRESHOLD and trend_up:
        tech_reasons = technical_confirms_buy(pattern, support, current_price, trend_slope)

        if REQUIRE_TECHNICAL_CONFIRMATION and not tech_reasons:
            print("ML BUY siqnalı var, amma texniki təsdiq yoxdur — siqnal ötürüldü.")
        else:
            # Texniki analiz support/resistance-a əsasən SL/TP-ni dəqiqləşdirir
            sl = support if support is not None else current_price - 1.5 * current_atr
            sl = min(sl, current_price - 0.5 * current_atr)  # SL çox yaxın olmasın
            tp = resistance if resistance is not None else current_price + 3.0 * current_atr
            tp = max(tp, current_price + 1.0 * current_atr)  # TP çox yaxın olmasın

            confidence_note = (
                f"✅ Texniki təsdiq: {', '.join(tech_reasons)}"
                if tech_reasons else "⚠️ Yalnız ML siqnalı (texniki təsdiq yoxdur)"
            )

            msg = (
                f"🚀 SİQNAL: ALIŞ (BUY)\n"
                f"Qiymət: {round(current_price, 5)}\n"
                f"SL: {round(sl, 5)}\n"
                f"TP: {round(tp, 5)}\n"
                f"Ehtimal: {prob:.0%} | Model dəqiqliyi: {test_acc:.0%}\n"
                f"Fiqur: {pattern}\n"
                f"{confidence_note}\n\n"
                f"{trends_block}"
            )
            send_telegram(msg)
            log_signal('BUY', current_price, sl, tp, prob, test_acc)
            signal_sent = True

    # ----------------------------------------------------------------- SELL
    elif prob < SELL_THRESHOLD and not trend_up:
        tech_reasons = technical_confirms_sell(pattern, resistance, current_price, trend_slope)

        if REQUIRE_TECHNICAL_CONFIRMATION and not tech_reasons:
            print("ML SELL siqnalı var, amma texniki təsdiq yoxdur — siqnal ötürüldü.")
        else:
            sl = resistance if resistance is not None else current_price + 1.5 * current_atr
            sl = max(sl, current_price + 0.5 * current_atr)
            tp = support if support is not None else current_price - 3.0 * current_atr
            tp = min(tp, current_price - 1.0 * current_atr)

            confidence_note = (
                f"✅ Texniki təsdiq: {', '.join(tech_reasons)}"
                if tech_reasons else "⚠️ Yalnız ML siqnalı (texniki təsdiq yoxdur)"
            )

            msg = (
                f"📉 SİQNAL: SATIŞ (SELL)\n"
                f"Qiymət: {round(current_price, 5)}\n"
                f"SL: {round(sl, 5)}\n"
                f"TP: {round(tp, 5)}\n"
                f"Ehtimal: {1 - prob:.0%} | Model dəqiqliyi: {test_acc:.0%}\n"
                f"Fiqur: {pattern}\n"
                f"{confidence_note}\n\n"
                f"{trends_block}"
            )
            send_telegram(msg)
            log_signal('SELL', current_price, sl, tp, 1 - prob, test_acc)
            signal_sent = True

    if not signal_sent:
        print(
            f"Siqnal göndərilmədi. prob={prob:.2f}, trend_up={trend_up}, "
            f"test_acc={test_acc:.2%}, pattern={pattern}"
        )


if __name__ == "__main__":
    run_bot()
