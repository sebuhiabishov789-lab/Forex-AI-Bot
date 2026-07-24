"""
economic_calendar.py v2.0 — Cache-li, fail-safe
"""
import requests
import json
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_FILE = "calendar_cache.json"
CACHE_HOURS = 4

RELEVANT_CURRENCIES = {"USD", "EUR"}
BLACKOUT_MINUTES_BEFORE = 30
BLACKOUT_MINUTES_AFTER = 30

def _load_cache():
    if not os.path.isfile(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data.get('timestamp', '2000-01-01T00:00:00+00:00'))
        if datetime.now(timezone.utc) - ts < timedelta(hours=CACHE_HOURS):
            return data.get('events', [])
    except Exception as e:
        logger.warning(f"Təqvim cache oxunmadı: {e}")
    return None

def _save_cache(events):
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump({'timestamp': datetime.now(timezone.utc).isoformat(), 'events': events}, f)
    except Exception as e:
        logger.warning(f"Təqvim cache yazılmadı: {e}")

def fetch_calendar_events(use_cache=True):
    if use_cache:
        cached = _load_cache()
        if cached is not None:
            return cached
    try:
        resp = requests.get(CALENDAR_URL, timeout=10, headers={'User-Agent': 'Forex-AI-Bot/2.0'})
        resp.raise_for_status()
        events = resp.json()
        if isinstance(events, list) and events:
            _save_cache(events)
            return events
    except Exception as e:
        logger.warning(f"Təqvim yüklənmədi: {e}")
        cached = _load_cache()
        if cached: return cached
    return []

def _parse_event_time(raw_date):
    if not raw_date: return None
    try:
        return datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        logger.warning(f"Xəbər vaxtı parse olunmadı ({raw_date!r}): {e}")
        return None

def check_news_blackout():
    events = fetch_calendar_events()
    if not events: return False, None, None
    now = datetime.now(timezone.utc)
    for ev in events:
        if ev.get("country") not in RELEVANT_CURRENCIES or ev.get("impact")!= "High":
            continue
        et = _parse_event_time(ev.get("date"))
        if not et: continue
        if (et - timedelta(minutes=BLACKOUT_MINUTES_BEFORE)) <= now <= (et + timedelta(minutes=BLACKOUT_MINUTES_AFTER)):
            return True, ev.get("title", "Naməlum"), et
    return False, None, None

def format_upcoming_high_impact(hours_ahead=24):
    events = fetch_calendar_events()
    if not events: return "Təqvim hazırda əlçatan deyil."
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours_ahead)
    upcoming = []
    for ev in events:
        if ev.get("country") not in RELEVANT_CURRENCIES or ev.get("impact")!= "High": continue
        et = _parse_event_time(ev.get("date"))
        if et and now <= et <= horizon:
            upcoming.append((et, ev.get("country"), ev.get("title","Naməlum")))
    if not upcoming: return f"Növbəti {hours_ahead} saatda yüksək təsirli xəbər yoxdur."
    upcoming.sort(key=lambda x: x[0])
    lines = [f"📅 Növbəti {hours_ahead} saatda:"]
    for t,c,title in upcoming:
        lines.append(f" {t.strftime('%d.%m %H:%M UTC')} [{c}] {title}")
    return "\n".join(lines)
