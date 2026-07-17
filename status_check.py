"""
status_check.py — Telegram-a gələn mesajları yoxlayır. Kimsə botа "indi" yazsa,
dərhal cari qiyməti, model ehtimalını və çoxlu zaman dilimi trendlərini göndərir.

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
import market_utils

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

OFFSET_FILE = "telegram_offset.txt"
TRIGGER_WORD = "indi"


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
    payload = {"chat_id": chat_id, "text": message}
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Telegram cavabı uğursuz: {resp.status_code} - {resp.text}")
    except requests.RequestException as e:
        print(f"Telegram xətası: {e}")


def build_status_message():
    status = market_utils.get_current_status()
    if status is None:
        return "⚠️ Hazırda kifayət qədər bazar datası yoxdur, bir az sonra yenidən cəhd edin."

    prob = status['prob']
    test_acc = status['test_acc']
    current_price = status['current_price']
    trend_up = status['trend_up']
    trends_block = market_utils.format_trends_block(status['mtf_trends'])

    trend_text = "🟢 Yuxarı" if trend_up else "🔴 Aşağı"

    msg = (
        f"📍 CARİ VƏZİYYƏT\n"
        f"Qiymət: {round(current_price, 5)}\n"
        f"Əsas trend (15dəq EMA20/50): {trend_text}\n"
        f"Modelin BUY ehtimalı: {prob:.0%}\n"
        f"Model test dəqiqliyi: {test_acc:.0%}\n\n"
        f"{trends_block}"
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
        save_offset(fallback_offset)  # fayl hər zaman mövcud olsun deyə
        return

    if not updates:
        print("Yeni mesaj yoxdur.")
        save_offset(fallback_offset)  # fayl hər zaman mövcud olsun deyə
        return

    max_update_id = fallback_offset

    for update in updates:
        update_id = update.get("update_id", 0)
        max_update_id = max(max_update_id, update_id + 1)

        # İlk işə düşmədə köhnə mesajlara cavab vermirik, sadəcə offset-i sinxronlaşdırırıq
        if first_run:
            continue

        message = update.get("message")
        if not message:
            continue

        text = message.get("text", "").strip().lower()
        sender_chat_id = str(message.get("chat", {}).get("id", ""))

        # Yalnız icazə verilmiş CHAT_ID-dən gələn mesajlara cavab veririk
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
