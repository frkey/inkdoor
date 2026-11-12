"""What the admin's Home shows about the day, worked out from a snapshot at render time: the
workday as a strip of blocks, and the door's word at its next change. Nothing here holds a
meeting title or a link."""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass

from .i18n import Translator
from .render import compute_status
from .sources import Snapshot


@dataclass
class Block:
    """One event on the timeline, clipped to the workday."""
    start: dt.datetime
    end: dt.datetime
    style: str                    # the calendar's marker: solid | striped | outline
    busy: bool


@dataclass
class Timeline:
    start: dt.datetime            # the workday's start today
    end: dt.datetime              # the workday's end today (the next midnight for 24)
    blocks: list[Block]


def build_timeline(snap: Snapshot, cfg: dict) -> Timeline | None:
    """Today's workday with its events, or None when there is no day to show: no busy calendar
    (the door does not follow a day then), a day off, or a busy calendar with no data at all
    (a strip without its events would read as free time, and nobody knows that)."""
    display = cfg["display"]
    if snap.configured != "busy" or snap.unknown or \
            snap.now.weekday() not in display["workdays"]:
        return None
    midnight = dt.datetime.combine(snap.now.date(), dt.time.min, snap.now.tzinfo)
    start = midnight + dt.timedelta(hours=display["workday_start"])
    end = midnight + dt.timedelta(hours=display["workday_end"])
    blocks = [Block(max(e.start, start), min(e.end, end), e.style, e.busy)
              for e in snap.today if not e.all_day and e.start < end and e.end > start]
    blocks = [b for b in blocks if b.start < b.end]
    return Timeline(start, end, sorted(blocks, key=lambda b: (b.start, b.end)))


def next_word(snap: Snapshot, cfg: dict, t: Translator, when: dt.datetime | None) -> str | None:
    """The door's word at ``when`` (its next change) as far as this snapshot knows, or None
    when there is no next change, nothing is set up, or the change is on another day (the
    status is worked out from today's events only)."""
    if when is None or snap.configured == "nothing" or when.date() != snap.now.date():
        return None
    return compute_status(dataclasses.replace(snap, now=when), cfg, t).word
