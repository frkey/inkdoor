"""`inkdoor check`: tests every link in the config and explains what is wrong."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import icalendar
import requests

from .config import is_configured
from .i18n import Translator
from .render import translator_for
from .sources import read_calendar, read_tasks

# Titles that mean the link only publishes free/busy, without details
FREE_BUSY_TITLES = {"busy", "ocupado", "tentative", "provisório", "free", "livre",
                    "away", "ausente", "working elsewhere", "trabalhando em outro lugar",
                    "out of office", "fora do escritório"}

OK, WARN, FAIL = "  ✔", "  ⚠", "  ✖"


def check_link(url: str, t: Translator) -> tuple[bool, str]:
    """Downloads the link and makes sure it is a calendar. Returns (ok, message)."""
    if not is_configured(url):
        return False, t("check.not_configured")
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    try:
        response = requests.get(url, timeout=30, headers={"User-Agent": "inkdoor"})
    except requests.RequestException as ex:
        return False, t("check.unreachable", error=ex.__class__.__name__)
    if response.status_code in (401, 403):
        return False, t("check.denied", status=response.status_code)
    if response.status_code == 404:
        return False, t("check.not_found")
    if response.status_code >= 400:
        return False, t("check.http_error", status=response.status_code)
    head = response.content[:2000]
    if b"BEGIN:VCALENDAR" not in head:
        return False, t("check.html_page") if b"<html" in head.lower() else t("check.not_ics")
    try:
        icalendar.Calendar.from_ical(response.content)
    except Exception:
        return False, t("check.invalid")
    return True, t("check.ok", kb=len(response.content) // 1024 or 1)


def run(cfg: dict) -> bool:
    t = translator_for(cfg)
    tz = ZoneInfo(cfg["display"]["timezone"])
    now = dt.datetime.now(tz)
    start = dt.datetime.combine(now.date(), dt.time.min, tz)
    end = start + dt.timedelta(days=14)
    all_ok = True

    for calendar in cfg.get("calendar", []):
        print(f"\n■ {calendar['name']}")
        ok, message = check_link(calendar.get("url", ""), t)
        print(OK if ok else FAIL, message)
        if not ok:
            all_ok = False
            continue
        events = [e for e in read_calendar(calendar, start, end, tz) if not e.all_day]
        if not events:
            print(WARN, t("check.no_events"))
            continue
        print(OK, t("check.events_found", n=len(events)))
        titles = {e.title.strip().lower() for e in events}
        if titles and titles <= FREE_BUSY_TITLES:
            print(WARN, t("check.busy_only"))
        for e in [e for e in events if e.end > now][:3]:
            print(f"     {e.start:%m/%d} {t.time(e.start):>8}  {e.title or t('untitled')}")
        # many events before 6 AM usually means a wrong time zone
        if len([e for e in events if e.start.hour < 6]) > len(events) / 3:
            print(WARN, t("check.timezone"))

    tasks_cfg = cfg.get("tasks")
    if tasks_cfg:
        print(f"\n■ {tasks_cfg.get('name', 'Tasks')}")
        ok, message = check_link(tasks_cfg.get("url", ""), t)
        print(OK if ok else FAIL, message)
        if ok:
            tasks = read_tasks(tasks_cfg, now.date(), tz)
            print(OK, t("check.tasks_found", n=len(tasks)))
            for task in tasks[:3]:
                print(f"     {t('check.overdue_prefix') if task.overdue else ''}{task.title or t('untitled')}")
        else:
            all_ok = False

    print("\n" + (t("check.all_good") if all_ok else t("check.fix_errors")))
    return all_ok
