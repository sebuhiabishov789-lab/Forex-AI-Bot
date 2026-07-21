"""
economic_calendar.py — ForexFactory-nin ictimai iqtisadi təqvim lentini yoxlayır.
Yüksək təsirli (High impact) USD/EUR xəbərlərinin ətrafında bot siqnal
göndərməkdən çəkinsin deyə "xəbər sükutu" (news blackout) müəyyən edir.

Qeyd: bu, açıq/ictimai bir JSON lentdir, API açarı tələb etmir. Format vaxtaşırı
dəyişə bilər — əgər fetch uğursuz olsa, funksiya "blackout yoxdur" qaytarır ki,
bot tam dayanmasın (fail-safe: xəbər yoxlaması işləməsə, bot adi rejimdə davam edir).
"""

import requests
from datetime import datetime, timezone, timedelta

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
RELEVANT_CURRENCIES = {"USD", "EUR"}
BLACKOUT_MINUTES_BEFORE = 30
BLACKOUT_MINUTES_AFTER = 30


def fetch_calendar_events():
    """İctimai JSON lentindən bu həftənin iqtisadi hadisələrini çəkir."""
    try:
        resp = requests.get(CALENDAR_URL, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"İqtisadi təqvim yüklənmədi (fail-safe: blackout yoxdur sayılır): {e}")
        return []


def _parse_event_time(raw_date):
    """Lentin tarix formatını (adətən ISO8601) datetime-a çevirir."""
    try:
        return datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def check_news_blackout():
    """
    Hazırda (və ya yaxın keçmişdə/gələcəkdə) yüksək təsirli USD/EUR xəbərinin
    "sükut pəncərəsində" olub-olmadığını yoxlayır.

    Qaytarır: (is_blackout: bool, event_title: str|None, event_time: datetime|None)
    """
    events = fetch_calendar_events()
    if not events:
        return False, None, None

    now = datetime.now(timezone.utc)

    for ev in events:
        try:
            country = ev.get("country")
            impact = ev.get("impact")
            if country not in RELEVANT_CURRENCIES or impact != "High":
                continue

            event_time = _parse_event_time(ev.get("date"))
            if event_time is None:
                continue

            window_start = event_time - timedelta(minutes=BLACKOUT_MINUTES_BEFORE)
            window_end = event_time + timedelta(minutes=BLACKOUT_MINUTES_AFTER)

            if window_start <= now <= window_end:
                return True, ev.get("title", "Naməlum hadisə"), event_time
        except (AttributeError, TypeError):
            continue

    return False, None, None


def format_upcoming_high_impact(hours_ahead=24):
    """Növbəti `hours_ahead` saat ərzindəki yüksək təsirli USD/EUR xəbərlərinin siyahısını mətn kimi qaytarır."""
    events = fetch_calendar_events()
    if not events:
        return "İqtisadi təqvim hazırda əlçatan deyil."

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours_ahead)
    upcoming = []

    for ev in events:
        country = ev.get("country")
        impact = ev.get("impact")
        if country not in RELEVANT_CURRENCIES or impact != "High":
            continue
        event_time = _parse_event_time(ev.get("date"))
        if event_time is None or not (now <= event_time <= horizon):
            continue
        upcoming.append((event_time, country, ev.get("title", "Naməlum hadisə")))

    if not upcoming:
        return f"Növbəti {hours_ahead} saatda yüksək təsirli USD/EUR xəbəri yoxdur."

    upcoming.sort(key=lambda x: x[0])
    lines = [f"📅 Növbəti {hours_ahead} saatda yüksək təsirli xəbərlər:"]
    for event_time, country, title in upcoming:
        lines.append(f"  {event_time.strftime('%d.%m %H:%M UTC')} [{country}] {title}")
    return "\n".join(lines)
