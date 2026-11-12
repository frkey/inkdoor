"""The night light schedule: when the Kindle's frontlight should be off.

``[display] light_off`` and ``light_on`` ("HH:MM", 24-hour, in ``display.timezone``) set a period
of the day, ``[light_off, light_on)``, that may cross midnight. The state follows local wall time,
so a daylight-saving change never shifts the period.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

_TIME = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")


def parse_time(value) -> dt.time | None:
    """The time for a "HH:MM" string (ASCII digits, 00:00 to 23:59), else None."""
    if not isinstance(value, str):
        return None
    match = _TIME.fullmatch(value)
    return dt.time(int(match.group(1)), int(match.group(2))) if match else None


def schedule(cfg: dict) -> tuple[dt.time, dt.time] | None:
    """(off, on) when both keys are set to valid times, else None (the feature is off)."""
    display = cfg.get("display", {})
    off, on = parse_time(display.get("light_off")), parse_time(display.get("light_on"))
    return (off, on) if off is not None and on is not None else None


def _local(now: dt.datetime, cfg: dict) -> dt.datetime:
    return now.astimezone(ZoneInfo(cfg["display"]["timezone"]))


def light_state(now: dt.datetime, cfg: dict) -> str:
    """"off" inside the period, "on" outside it or when no schedule is set. ``now`` is aware."""
    times = schedule(cfg)
    if times is None:
        return "on"
    off, on = times
    t = _local(now, cfg).time().replace(second=0, microsecond=0)
    inside = off <= t < on if off < on else (t >= off or t < on)
    return "off" if inside else "on"


def next_light_change(now: dt.datetime, cfg: dict) -> dt.datetime | None:
    """The next moment after ``now`` at which the light turns off or on, in the display time zone;
    None when no schedule is set. Boundaries are compared as instants, not as wall times."""
    times = schedule(cfg)
    if times is None:
        return None
    local = _local(now, cfg)
    today = local.date()
    candidates = [dt.datetime.combine(day, t, local.tzinfo)
                  for day in (today, today + dt.timedelta(days=1)) for t in times]
    return min((c for c in candidates if c.timestamp() > now.timestamp()),
               key=lambda c: c.timestamp())
