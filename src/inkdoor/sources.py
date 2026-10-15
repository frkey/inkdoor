"""Reads calendars (ICS) and tasks (TickTick subscription) into one model."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

from .config import is_configured

# Online-meeting locations only add noise on the screen
_ONLINE_LOCATION = re.compile(r"teams|zoom|meet\.google|http", re.I)
# Outlook prefixes the title instead of setting STATUS in some exports
_CANCELLED_PREFIXES = ("canceled:", "cancelled:", "cancelado:", "cancelada:")


@dataclass
class Event:
    start: dt.datetime
    end: dt.datetime
    title: str                      # may be empty; the renderer shows "(untitled)"
    source: str                     # calendar name from the config
    style: str = "solid"            # solid | striped | outline
    busy: bool = True               # whether it makes the door status "busy"
    status_label: str | None = None  # big word on the door; None = translated default
    all_day: bool = False
    location: str = ""
    extra_sources: list = field(default_factory=list)

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Task:
    title: str
    due: dt.date
    time: dt.time | None = None
    priority: int = 0               # 0 none, 1 low, 2 medium, 3 high
    overdue: bool = False


@dataclass
class Snapshot:
    now: dt.datetime
    today: list
    tomorrow: list
    tasks: list
    errors: list                    # names of sources that could not be read


# ---------------------------------------------------------------- reading

def fetch(url: str) -> bytes:
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if url.startswith("http"):
        response = requests.get(url, timeout=30, headers={"User-Agent": "inkdoor"})
        response.raise_for_status()
        return response.content
    with open(url, "rb") as f:      # local file, handy for tests
        return f.read()


def _to_local(value, tz):
    if isinstance(value, dt.datetime):
        return (value if value.tzinfo else value.replace(tzinfo=tz)).astimezone(tz)
    return dt.datetime.combine(value, dt.time.min, tz)


def _occurrences(cal, start, end, components=("VEVENT",)):
    try:
        return recurring_ical_events.of(cal, components=list(components)).between(start, end)
    except TypeError:  # older versions of the library
        return recurring_ical_events.of(cal).between(start, end)


def read_calendar(calendar: dict, start: dt.datetime, end: dt.datetime, tz) -> list[Event]:
    cal = icalendar.Calendar.from_ical(fetch(calendar["url"]))
    events = []
    for item in _occurrences(cal, start, end):
        if str(item.get("STATUS", "")).upper() == "CANCELLED":
            continue
        title = str(item.get("SUMMARY", "")).strip()
        if title.lower().startswith(_CANCELLED_PREFIXES):
            continue
        raw_start = item["DTSTART"].dt
        all_day = not isinstance(raw_start, dt.datetime)
        ev_start = _to_local(raw_start, tz)
        if "DTEND" in item:
            ev_end = _to_local(item["DTEND"].dt, tz)
        elif "DURATION" in item:
            ev_end = ev_start + item["DURATION"].dt
        else:
            ev_end = ev_start + (dt.timedelta(days=1) if all_day else dt.timedelta(minutes=30))
        transparent = str(item.get("TRANSP", "")).upper() == "TRANSPARENT"
        location = str(item.get("LOCATION", "")).strip()
        if _ONLINE_LOCATION.search(location):
            location = ""
        events.append(Event(
            start=ev_start, end=ev_end, title=title,
            source=calendar["name"],
            style=calendar.get("style", "solid"),
            busy=calendar.get("busy", True) and not transparent and not all_day,
            status_label=calendar.get("status_label"),
            all_day=all_day, location=location,
        ))
    return events


def read_tasks(tasks_cfg: dict, today: dt.date, tz) -> list[Task]:
    cal = icalendar.Calendar.from_ical(fetch(tasks_cfg["url"]))
    overdue_days = int(tasks_cfg.get("overdue_days", 7))
    start = dt.datetime.combine(today - dt.timedelta(days=overdue_days), dt.time.min, tz)
    end = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.min, tz)
    tasks, seen = [], set()
    for item in _occurrences(cal, start, end, ("VEVENT", "VTODO")):
        if str(item.get("STATUS", "")).upper() in ("COMPLETED", "CANCELLED") or "COMPLETED" in item:
            continue
        when = item.get("DUE") or item.get("DTSTART")
        if when is None:
            continue
        value = when.dt
        if isinstance(value, dt.datetime):
            value = _to_local(value, tz)
            due, time = value.date(), (value.time() if (value.hour, value.minute) != (0, 0) else None)
        else:
            due, time = value, None
        if due > today:
            continue
        title = str(item.get("SUMMARY", "")).strip()
        key = (title.lower(), due)
        if key in seen:
            continue
        seen.add(key)
        ical_priority = int(item.get("PRIORITY", 0) or 0)  # iCal: 1 = highest, 9 = lowest
        priority = 3 if 1 <= ical_priority <= 4 else 2 if ical_priority == 5 else 1 if ical_priority >= 6 else 0
        tasks.append(Task(title=title, due=due, time=time, priority=priority, overdue=due < today))
    return sort_tasks(tasks)


def sort_tasks(tasks: list[Task]) -> list[Task]:
    return sorted(tasks, key=lambda t: (not t.overdue, t.time is None, t.time or dt.time.min,
                                        -t.priority, t.title.lower()))


# ---------------------------------------------------------------- merging

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def deduplicate(events: list[Event]) -> list[Event]:
    """Drops repeated events inside the same calendar. Different calendars never merge."""
    unique: dict = {}
    for ev in events:
        key = (ev.source, _normalize(ev.title), ev.start.replace(second=0, microsecond=0), ev.all_day)
        if key in unique:
            unique[key].busy = unique[key].busy or ev.busy
        else:
            unique[key] = ev
    return sorted(unique.values(), key=lambda e: (not e.all_day, e.start, e.end))


def collect(cfg: dict, now: dt.datetime | None = None) -> Snapshot:
    tz = ZoneInfo(cfg["display"]["timezone"])
    now = now or dt.datetime.now(tz)
    today = now.date()
    day_start = dt.datetime.combine(today, dt.time.min, tz)
    tomorrow_start = day_start + dt.timedelta(days=1)
    window_end = day_start + dt.timedelta(days=2)

    events, errors = [], []
    for calendar in cfg.get("calendar", []):
        if not is_configured(calendar.get("url")):
            continue
        try:
            events += read_calendar(calendar, day_start, window_end, tz)
        except Exception as ex:  # one broken calendar must not take the screen down
            errors.append(f"{calendar['name']}: {ex.__class__.__name__}")

    tasks = []
    tasks_cfg = cfg.get("tasks")
    if tasks_cfg and is_configured(tasks_cfg.get("url")):
        try:
            tasks = read_tasks(tasks_cfg, today, tz)
        except Exception as ex:
            errors.append(f"{tasks_cfg.get('name', 'Tasks')}: {ex.__class__.__name__}")

    events = deduplicate(events)
    today_events = [e for e in events if e.start < tomorrow_start and e.end > day_start]
    tomorrow_events = [e for e in events if e.start < window_end and e.end > tomorrow_start
                       and not (e.all_day and e.start < tomorrow_start)]
    return Snapshot(now, today_events, tomorrow_events, tasks, errors)
