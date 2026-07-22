import requests
import time
import threading

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from main import run_bot


def get_updates(offset=None):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    params = {}

    if offset:
        params["offset"] = offset

    return requests.get(url, params=params).json()


def send_reply(text):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text
        }
    )


def auto_monitor():

    last_signal = ""

    while True:

        try:
            result = run_bot()

            if result and ("Qerar: AL" in result or "Qerar: SAT" in result):

                if result != last_signal:
                    send_reply(result)
                    last_signal = result

        except Exception as e:
            print(e)

        time.sleep(300)


def start():

    offset = None

    while True:

        try:

            data = get_updates(offset)

            for item in data.get("result", []):

                offset = item["update_id"] + 1

                text = item["message"]["text"].lower()

                if text == "now":

                    result = run_bot()

                    if result:
                        send_reply(result)

        except Exception as e:
            print(e)

        time.sleep(2)


if __name__ == "__main__":

    threading.Thread(
        target=auto_monitor,
        daemon=True
    ).start()

    start()
