"""Reads calendars (ICS) and tasks (TickTick subscription) into one model."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from . import files, isolate, net
from .config import is_configured

# Online-meeting locations only add noise on the screen
_ONLINE_LOCATION = re.compile(r"teams|zoom|meet\.google|http", re.I)
# Outlook prefixes the title instead of setting STATUS in some exports
_CANCELLED_PREFIXES = ("canceled:", "cancelled:", "cancelado:", "cancelada:")
# Occurrences the expansion of one source may go through. A real calendar has a few dozen in two
# days, and a task list a few thousand at most over a year of overdue days; a rule that repeats
# every second has 172,800 in two days. Each costs a few KB while the child reads.
MAX_OCCURRENCES = 20000
# The library orders dates and floating times without our time zone, so its order can be off by up
# to a UTC offset: the expansion goes this far past the window before it stops.
_ORDER_SLACK = dt.timedelta(days=1)


class TooManyOccurrences(Exception):
    """A calendar has more occurrences in the window than MAX_OCCURRENCES."""


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
    errors: list = field(default_factory=list)     # "Name: ErrorType" for sources that failed
    unknown: list = field(default_factory=list)    # busy calendars with no data at all right now
    # What has a link: "nothing" (no calendar and no tasks), "no_busy" (something, but no busy
    # calendar) or "busy" (at least one busy calendar). The renderer never says Free unless "busy".
    configured: str = "busy"
    # one SourceHealth per calendar and for the task list, in config order (the admin's Home)
    health: list = field(default_factory=list)


@dataclass
class SourceHealth:
    """How one source did in this read, in words the admin can show: never a link, never an
    exception's text."""
    kind: str                     # "calendar" | "tasks"
    name: str
    style: str | None             # the calendar's marker; None for tasks
    busy: bool
    state: str                    # "ok" | "stale" (failed, using today's earlier read) |
    #                               "failed" (no data today) | "unset" (no link yet)
    items: int                    # events today (calendar) or tasks shown; 0 when failed or unset
    read_at: dt.datetime | None   # when the data in use was read; None when failed or unset
    reason: str | None            # failure category when stale or failed, else None


def failure_reason(ex: Exception) -> str:
    """Why a read failed, as one of a few categories: "timeout", "denied", "not_found", "http",
    "unreachable" or "other"."""
    if isinstance(ex, isolate.CalendarTimeout):
        return "timeout"
    if isinstance(ex, net.FetchError):
        if ex.reason == "timeout":
            return "timeout"
        if ex.reason == "http":
            return {401: "denied", 403: "denied", 404: "not_found"}.get(ex.status, "http")
        return "unreachable"
    return "other"


def cache_key(kind: str, name: str, url: str) -> tuple[str, str, str]:
    """Cache key for a source: its kind ("calendar" or "tasks"), its name and a hash of its link
    (the link itself is never stored). The kind keeps a calendar from sharing the tasks' key."""
    return (kind, name, hashlib.sha256(url.encode("utf-8")).hexdigest())


class SourceCache:
    """Last good data per source, reused when a fetch fails.

    A flaky calendar link must never flip the door to "Free" in the middle of a meeting, so
    the server keeps the last successful read of each source for the current day. Entries are
    keyed by kind, name and link, so a replaced link never falls back to the old link's data, and
    `keep` drops the entries of sources that are no longer in the config.

    With a ``path`` the entries are also kept in a private file (`save`), which a new process
    starts from: a restart while a calendar is failing must not take the day's data away. The
    file holds what the calendars hold (titles, times), so it is mode 600 and is never served; a
    missing or damaged file is the same as no file.
    """

    def __init__(self, path: str | None = None):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = _load_cache(path) if path else {}
        self._dirty = False

    def put(self, key: tuple, day: dt.date, items: list, at: dt.datetime | None = None) -> None:
        """Keeps a good read; ``at`` is when it was made."""
        with self._lock:
            self._data[key] = (day, items, at)
            self._dirty = True

    def get(self, key: tuple, day: dt.date):
        with self._lock:
            cached = self._data.get(key)
        return cached[1] if cached and cached[0] == day else None

    def read_at(self, key: tuple, day: dt.date) -> dt.datetime | None:
        """When the data ``get`` returns for that day was read, if known."""
        with self._lock:
            cached = self._data.get(key)
        return cached[2] if cached and cached[0] == day else None

    def keep(self, keys: set) -> None:
        """Drops every entry whose key is not in `keys`."""
        with self._lock:
            kept = {key: value for key, value in self._data.items() if key in keys}
            self._dirty = self._dirty or len(kept) != len(self._data)
            self._data = kept

    def save(self) -> None:
        """Writes the entries to the file when something changed since the last save.

        Raises OSError when the file cannot be written; the entries stay in memory and the next
        save tries again.
        """
        if not self._path:
            return
        with self._lock:
            if not self._dirty:
                return
            data = _dump_cache(self._data)
            self._dirty = False
        try:
            files.write_private(self._path, data)
        except BaseException:
            with self._lock:
                self._dirty = True
            raise


# The cache file: JSON only (never pickle: loading it must not be able to run anything).
_CACHE_VERSION = 1


def _dump_cache(data: dict) -> bytes:
    entries = [{"key": list(key), "day": day.isoformat(),
                "at": at.isoformat() if at is not None else None,
                "items": [_dump_item(item) for item in items]}
               for key, (day, items, at) in data.items()]
    return json.dumps({"version": _CACHE_VERSION, "sources": entries},
                      ensure_ascii=False).encode("utf-8")


def _dump_item(item) -> dict:
    if isinstance(item, Event):
        return {"type": "event", "start": item.start.isoformat(), "end": item.end.isoformat(),
                "title": item.title, "source": item.source, "style": item.style,
                "busy": item.busy, "status_label": item.status_label, "all_day": item.all_day,
                "location": item.location}
    return {"type": "task", "title": item.title, "due": item.due.isoformat(),
            "time": item.time.isoformat() if item.time is not None else None,
            "priority": item.priority, "overdue": item.overdue}


def _load_cache(path: str) -> dict:
    """The entries of a cache file; nothing when the file is missing, damaged or from a version
    this code does not know. One bad entry drops the whole file: half a day is not the day."""
    try:
        with open(path, "rb") as f:
            raw = json.loads(f.read().decode("utf-8"))
        if raw["version"] != _CACHE_VERSION:
            return {}
        data = {}
        for entry in raw["sources"]:
            kind, name, digest = entry["key"]
            at = _aware(entry["at"]) if entry["at"] is not None else None
            items = [_load_item(item) for item in entry["items"]]
            data[(_typed(kind, str), _typed(name, str), _typed(digest, str))] = (
                dt.date.fromisoformat(entry["day"]), items, at)
        return data
    except Exception:  # whatever is wrong with it, the server starts as it does without a file
        return {}


def _typed(value, kind: type):
    if type(value) is not kind:
        raise ValueError
    return value


def _aware(text: str) -> dt.datetime:
    """A saved moment. It comes back with the UTC offset it had, which is the same instant and
    the same wall clock as before the restart."""
    moment = dt.datetime.fromisoformat(_typed(text, str))
    if moment.tzinfo is None:
        raise ValueError
    return moment


def _load_item(raw: dict):
    if raw["type"] == "event":
        label = raw["status_label"]
        return Event(_aware(raw["start"]), _aware(raw["end"]), _typed(raw["title"], str),
                     _typed(raw["source"], str), _typed(raw["style"], str),
                     _typed(raw["busy"], bool), None if label is None else _typed(label, str),
                     _typed(raw["all_day"], bool), _typed(raw["location"], str))
    if raw["type"] == "task":
        time = raw["time"]
        return Task(_typed(raw["title"], str), dt.date.fromisoformat(_typed(raw["due"], str)),
                    None if time is None else dt.time.fromisoformat(_typed(time, str)),
                    _typed(raw["priority"], int), _typed(raw["overdue"], bool))
    raise ValueError


# ---------------------------------------------------------------- reading

def fetch(url: str) -> bytes:
    """Downloads a link (or reads a local file) through the capped, SSRF-aware helper."""
    return net.fetch(url)


def _to_local(value, tz):
    if isinstance(value, dt.datetime):
        return (value if value.tzinfo else value.replace(tzinfo=tz)).astimezone(tz)
    return dt.datetime.combine(value, dt.time.min, tz)


def _start(item, tz):
    """When an occurrence starts, in ``tz``; None when it has no date to go by."""
    when = item.get("DTSTART") or item.get("DUE")
    return None if when is None else _to_local(when.dt, tz)


def _occurrences(cal, start, end, tz, components=("VEVENT",)):
    """Occurrences that overlap [start, end). The library yields them lazily, in order of start,
    so the expansion stops just past ``end`` and goes through at most MAX_OCCURRENCES."""
    found = []
    query = recurring_ical_events.of(cal, components=list(components))
    for seen, item in enumerate(query.after(start)):
        if seen == MAX_OCCURRENCES:
            raise TooManyOccurrences()
        begins = _start(item, tz)
        if begins is not None and begins >= end:
            if begins >= end + _ORDER_SLACK:
                break
            continue
        found.append(item)
    return found


def read_calendar(calendar: dict, start: dt.datetime, end: dt.datetime, tz) -> list[Event]:
    return events_from(fetch(calendar["url"]), calendar, start, end, tz)


def events_from(content: bytes, calendar: dict, start: dt.datetime, end: dt.datetime,
                tz) -> list[Event]:
    """Events of a downloaded calendar between start and end, read in a child process with a
    time limit (see ``isolate``): a calendar is data from outside."""
    return isolate.run(_events_from, content, calendar, start, end, tz)


def _events_from(content: bytes, calendar: dict, start, end, tz) -> list[Event]:
    return parse_events(icalendar.Calendar.from_ical(content), calendar, start, end, tz)


def parse_events(cal, calendar: dict, start: dt.datetime, end: dt.datetime, tz) -> list[Event]:
    """Events of an already parsed calendar between start and end, in this process."""
    events = []
    for item in _occurrences(cal, start, end, tz):
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
    return tasks_from(fetch(tasks_cfg["url"]), tasks_cfg, today, tz)


def tasks_from(content: bytes, tasks_cfg: dict, today: dt.date, tz) -> list[Task]:
    """Tasks of a downloaded calendar due today or overdue, read in a child process (see
    ``events_from``)."""
    return isolate.run(_tasks_from, content, tasks_cfg, today, tz)


def _tasks_from(content: bytes, tasks_cfg: dict, today: dt.date, tz) -> list[Task]:
    return parse_tasks(icalendar.Calendar.from_ical(content), tasks_cfg, today, tz)


def parse_tasks(cal, tasks_cfg: dict, today: dt.date, tz) -> list[Task]:
    """Tasks of an already parsed calendar that are due today or overdue, in this process."""
    overdue_days = int(tasks_cfg.get("overdue_days", 7))
    start = dt.datetime.combine(today - dt.timedelta(days=overdue_days), dt.time.min, tz)
    end = dt.datetime.combine(today + dt.timedelta(days=1), dt.time.min, tz)
    tasks, seen = [], set()
    for item in _occurrences(cal, start, end, tz, ("VEVENT", "VTODO")):
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


def collect(cfg: dict, now: dt.datetime | None = None, cache: SourceCache | None = None) -> Snapshot:
    tz = ZoneInfo(cfg["display"]["timezone"])
    now = now or dt.datetime.now(tz)
    today = now.date()
    day_start = dt.datetime.combine(today, dt.time.min, tz)
    tomorrow_start = day_start + dt.timedelta(days=1)
    window_end = day_start + dt.timedelta(days=2)

    events, errors, unknown, keys, health = [], [], [], set(), []
    any_configured = busy_configured = False

    def failed(source: SourceHealth, key: tuple, ex: Exception):
        """Notes the failure and returns today's earlier read of that source, if there is one."""
        errors.append(f"{source.name}: {ex.__class__.__name__}")
        cached = cache.get(key, today) if cache is not None else None
        source.state = "failed" if cached is None else "stale"
        source.read_at = None if cached is None else cache.read_at(key, today)
        source.reason = failure_reason(ex)
        return cached

    for calendar in cfg.get("calendar", []):
        busy = bool(calendar.get("busy", True))
        source = SourceHealth("calendar", str(calendar.get("name", "")),
                              calendar.get("style", "solid"), busy, "unset", 0, None, None)
        health.append(source)
        if not is_configured(calendar.get("url")):
            continue
        any_configured = True
        busy_configured = busy_configured or busy
        name = calendar["name"]
        key = cache_key("calendar", name, calendar["url"])
        keys.add(key)
        try:
            fresh = read_calendar(calendar, day_start, window_end, tz)
            if cache is not None:
                cache.put(key, today, fresh, now)
            events += fresh
            source.state, source.read_at = "ok", now
        except Exception as ex:  # one broken calendar must not take the screen down
            cached = failed(source, key, ex)
            if cached is not None:
                events += cached
            elif busy:
                unknown.append(name)

    tasks = []
    tasks_cfg = cfg.get("tasks")
    tasks_health = None
    if tasks_cfg:
        tasks_health = SourceHealth("tasks", str(tasks_cfg.get("name", "TickTick")), None, False,
                                    "unset", 0, None, None)
        health.append(tasks_health)
    if tasks_cfg and is_configured(tasks_cfg.get("url")):
        any_configured = True
        name = tasks_cfg.get("name", "TickTick")
        key = cache_key("tasks", name, tasks_cfg["url"])
        keys.add(key)
        try:
            tasks = read_tasks(tasks_cfg, today, tz)
            if cache is not None:
                cache.put(key, today, tasks, now)
            tasks_health.state, tasks_health.read_at = "ok", now
        except Exception as ex:
            tasks = failed(tasks_health, key, ex) or []
        tasks_health.items = len(tasks)

    if cache is not None:
        cache.keep(keys)                 # links replaced or removed since the last cycle

    events = deduplicate(events)
    today_events = [e for e in events if e.start < tomorrow_start and e.end > day_start]
    tomorrow_events = [e for e in events
                       if (e.all_day and e.start < window_end and e.end > tomorrow_start)
                       or (not e.all_day and tomorrow_start <= e.start < window_end)]
    configured = "busy" if busy_configured else "no_busy" if any_configured else "nothing"
    for source in health:
        if source.kind == "calendar" and source.state in ("ok", "stale"):
            source.items = sum(1 for e in today_events if e.source == source.name)
    return Snapshot(now, today_events, tomorrow_events, tasks, errors, unknown, configured, health)
