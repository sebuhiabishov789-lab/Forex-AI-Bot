"""
status_check.py — Telegram-a gələn mesajları yoxlayır. Kimsə bota "indi" yazsa,
dərhal cari qiyməti, model ehtimalını, çoxlu zaman dilimi trendlərini,
texniki göstəriciləri (ATR, RSI, MACD, support/resistance),
model razılaşmasını, son siqnal performansını və növbəti yüksək təsirli
iqtisadi xəbərləri göndərir.

Bu skript ayrıca bir GitHub Actions workflow-u vasitəsilə tez-tez (məs. hər 5 dəqiqədən
bir) işə düşməlidir ki, gələn mesajları vaxtında görsün (tam "real-time" deyil,
polling əsaslı — bir neçə dəqiqəlik gecikmə ola bilər).

Telegram-ın getUpdates API-si offset əsaslıdır: hər dəfə son görülən update_id-dən
sonrakıları çəkirik ki, eyni mesaja iki dəfə cavab verilməsin. Bu offset
telegram_offset.txt faylında saxlanılır və hər run-dan sonra commit edilməlidir
(workflow-da git commit addımı ilə).
"""

import requests
import os
import csv
from datetime import datetime, timezone, timedelta
import market_utils
import economic_calendar

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

OFFSET_FILE = "telegram_offset.txt"
TRIGGER_WORD = "indi"
LOG_FILE = "signals_log.csv"


def get_saved_offset():
    if os.path.isfile(OFFSET_FILE):
        with open(OFFSET_FILE, 'r') as f:
            content = f.read().strip()
            if content.isdigit():
                return int(content)
    return None


def save_offset(update_id):
    with open(OFFSET_FILE, 'w') as f:
        f.write(str(update_id))


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])


def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Telegram cavabı uğursuz: {resp.status_code} - {resp.text}")
            # Markdown uyğunsuzluğu halında sadə mətnlə yenidən cəhd
            payload["parse_mode"] = ""
            requests.post(url, data=payload, timeout=15)
    except requests.RequestException as e:
        print(f"Telegram xətası: {e}")


def get_market_session():
    """UTC vaxta əsasən hansı bazar sessiyasının aktiv olduğunu qaytarır."""
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    if 7 <= hour < 16:
        return "🇪🇺 London"
    elif 13 <= hour < 21:
        return "🇺🇸 Nyu-York"
    elif 0 <= hour < 9:
        return "🇯🇵 Asiya"
    else:
        return "🌐 Qarışıq"


def get_recent_performance():
    """Son 5 qapalı siqnal üzrə qazanc/ziyan xülasəsini qaytarır."""
    if not os.path.isfile(LOG_FILE):
        return None
    results = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('outcome') and row['outcome'] != 'OPEN':
                    results.append(row)
    except Exception:
        return None
    if not results:
        return None
    # Son 5 qapalı siqnalı götür
    recent = results[-5:]
    wins = sum(1 for r in recent if r.get('outcome') == 'WIN')
    losses = len(recent) - wins
    pips = [float(r['pip_result']) for r in recent if r.get('pip_result')]
    total_pips = sum(pips) if pips else 0
    summary = f"Son {len(recent)} əməl: {wins}✅ qazanc, {losses}❌ zərər"
    if total_pips != 0:
        summary += f" | Pip: {'+' if total_pips>0 else ''}{total_pips:.1f}"
    return summary


def build_status_message():
    status = market_utils.get_current_status()
    if status is None:
        return "⚠️ Hazırda kifayət qədər bazar datası yoxdur, bir az sonra yenidən cəhd edin."

    # Əsas məlumatlar
    prob = status['prob']
    test_acc = status['test_acc']
    current_price = status['current_price']
    current_atr = status['current_atr']
    trend_up = status['trend_up']
    trend_slope = status['trend_slope']
    pattern = status['pattern']
    support = status['support']
    resistance = status['resistance']
    rf_prob = status['rf_prob']
    gb_prob = status['gb_prob']
    model_agreement = status['model_agreement']
    aligned_tf_up = status['aligned_tf_up']
    aligned_tf_down = status['aligned_tf_down']

    trends_block = market_utils.format_trends_block(status['mtf_trends'])

    session = get_market_session()

    # Trend əmsalı detalı
    if trend_slope > 0.0001:
        slope_desc = "kəskin yuxarı ⬆️"
    elif trend_slope > 0:
        slope_desc = "zəif yuxarı ↗️"
    elif trend_slope < -0.0001:
        slope_desc = "kəskin aşağı ⬇️"
    elif trend_slope < 0:
        slope_desc = "zəif aşağı ↘️"
    else:
        slope_desc = "üfüqi ➖"

    # Model razılaşma detalı
    if model_agreement == 1.0:
        agreement_text = "✅ Hər iki model razı"
    else:
        rf_dir = "BUY" if rf_prob > 0.5 else "SELL"
        gb_dir = "BUY" if gb_prob > 0.5 else "SELL"
        agreement_text = f"⚠️ Fərqli: RF={rf_dir}, GB={gb_dir}"

    # Uyğunlaşan TF sayları
    tf_alignment_text = f"📈 BUY: {aligned_tf_up}/5 TF  |  📉 SELL: {aligned_tf_down}/5 TF"

    # Xəbər bloku
    news_block = economic_calendar.format_upcoming_high_impact(hours_ahead=24)
    is_blackout, event_title, event_time = economic_calendar.check_news_blackout()
    blackout_note = ""
    if is_blackout:
        event_time_str = event_time.strftime('%H:%M UTC') if event_time else "?"
        blackout_note = f"⚠️ XƏBƏR SÜKUTU: {event_title} ({event_time_str})"

    # Son performans
    perf = get_recent_performance()
    perf_block = f"📊 Performans: {perf}\n" if perf else ""

    # Support/Resistance bloku
    sr_block = ""
    if support is not None:
        sr_block += f"🟢 Dəstək: {support:.5f}\n"
    if resistance is not None:
        sr_block += f"🔴 Direnc: {resistance:.5f}\n"

    # Ana mesaj
    msg = (
        f"📍 *Bazar Statusu*\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}  |  {session}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Qiymət: {current_price:.5f}\n"
        f"📏 ATR (15m): {current_atr:.5f}\n"
        f"{sr_block}"
        f"🔹 Trend: {'🟢 UP' if trend_up else '🔴 DOWN'} (meyl: {slope_desc})\n"
        f"🔹 Trend əmsalı: {trend_slope:.6f}\n"
        f"📐 Fiqur: {pattern}\n"
        f"\n🧠 *Model Proqnozu*\n"
        f"🎯 RF: {rf_prob:.1%}  |  GB: {gb_prob:.1%}\n"
        f"🔮 Ensemble: {prob:.1%}  |  Dəqiqlik: {test_acc:.1%}\n"
        f"🤝 Razılaşma: {agreement_text}\n"
        f"{tf_alignment_text}\n"
        f"{blackout_note}\n"
        f"{perf_block}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Trend (Çoxzamanlı)*\n{trends_block}\n\n"
        f"📰 *İqtisadi Təqvim*\n{news_block}"
    )
    return msg


def run():
    if not TOKEN or not CHAT_ID:
        print("TOKEN/CHAT_ID tapılmadı, dayandırılır.")
        return

    saved_offset = get_saved_offset()
    first_run = saved_offset is None
    fallback_offset = saved_offset if saved_offset is not None else 0

    try:
        updates = get_updates(offset=saved_offset)
    except requests.RequestException as e:
        print(f"getUpdates xətası: {e}")
        save_offset(fallback_offset)
        return

    if not updates:
        print("Yeni mesaj yoxdur.")
        save_offset(fallback_offset)
        return

    max_update_id = fallback_offset

    for update in updates:
        update_id = update.get("update_id", 0)
        max_update_id = max(max_update_id, update_id + 1)

        if first_run:
            continue

        message = update.get("message")
        if not message:
            continue

        text = message.get("text", "").strip().lower()
        sender_chat_id = str(message.get("chat", {}).get("id", ""))

        if sender_chat_id != str(CHAT_ID):
            print(f"Naməlum chat_id-dən mesaj gəldi ({sender_chat_id}), nəzərə alınmadı.")
            continue

        if text == TRIGGER_WORD:
            print("'indi' sözü tapıldı, status hazırlanır...")
            status_msg = build_status_message()
            send_telegram(sender_chat_id, status_msg)

    save_offset(max_update_id)

    if first_run:
        print("İlk işə düşmə: offset sinxronlaşdırıldı, köhnə mesajlara cavab verilmədi.")


if __name__ == "__main__":
    run()
