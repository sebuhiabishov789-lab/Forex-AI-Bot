"""
outcome_tracker.py — Açıq qalmış siqnalları cari qiymətlə müqayisə edir,
SL/TP-yə çatıbsa, nəticəni (WIN/LOSS), bağlanma vaxtını və pip fərqini
signals_log.csv faylında yeniləyir.

Bu skript hər 15-30 dəqiqədən bir GitHub Actions ilə işə salınmalıdır.
"""

import os
import csv
import market_utils

LOG_FILE = "signals_log.csv"
PIP_VALUE = float(os.environ.get('PIP_VALUE', 0.0001))  # bot.py ilə eyni


def load_signals():
    """CSV faylındakı bütün siqnalları oxuyur, başlıqları saxlayır."""
    rows = []
    fieldnames = []
    if os.path.isfile(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)
    return fieldnames, rows


def save_signals(fieldnames, rows):
    """Dəyişiklikləri CSV faylına geri yazır."""
    with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def update_outcome(row, status):
    """
    Cari qiymətə əsasən siqnalın nəticəsini təyin edir.
    Qaytarır: (outcome, closed_at, pip_result) — əgər bağlanmalıdırsa.
    """
    direction = row.get('direction', '').upper()
    try:
        entry = float(row['entry'])
        sl = float(row['sl'])
        tp = float(row['tp'])
    except (ValueError, KeyError):
        return None, None, None

    current_price = status['current_price']

    # Bağlanma şərtləri
    if direction == 'BUY':
        if current_price >= tp:
            outcome = 'WIN'
            closed_price = tp
        elif current_price <= sl:
            outcome = 'LOSS'
            closed_price = sl
        else:
            return None, None, None  # hələ açıqdır

        pip_diff = (closed_price - entry) / PIP_VALUE
    elif direction == 'SELL':
        if current_price <= tp:
            outcome = 'WIN'
            closed_price = tp
        elif current_price >= sl:
            outcome = 'LOSS'
            closed_price = sl
        else:
            return None, None, None

        pip_diff = (entry - closed_price) / PIP_VALUE
    else:
        return None, None, None

    return outcome, closed_price, round(pip_diff, 1)


def run():
    status = market_utils.get_current_status()
    if status is None:
        print("Bazar datası alınmadı, izləmə dayandırıldı.")
        return

    fieldnames, rows = load_signals()
    if not fieldnames or not rows:
        print("Siqnal faylı boşdur və ya mövcud deyil.")
        return

    updated = False
    from datetime import datetime, timezone

    for row in rows:
        if row.get('outcome', '').upper() != 'OPEN':
            continue  # artıq bağlanıb

        outcome, closed_price, pip_result = update_outcome(row, status)
        if outcome:
            row['outcome'] = outcome
            row['closed_at'] = datetime.now(timezone.utc).isoformat()
            row['pip_result'] = pip_result
            print(f"Siqnal {row.get('signal_id', '?')} bağlandı: {outcome}, Pip: {pip_result}")
            updated = True

    if updated:
        save_signals(fieldnames, rows)
    else:
        print("Açıq siqnal tapılmadı və ya heç biri bağlanma şərtini ödəmədi.")


if __name__ == "__main__":
    run()
