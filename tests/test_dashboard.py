"""The timeline and the next status word the admin's Home shows."""
import datetime as dt

from helpers import TZ, at

from inkdoor.config import with_defaults
from inkdoor.dashboard import build_timeline, next_word
from inkdoor.i18n import Translator
from inkdoor.sources import Event, Snapshot

# 2026-10-14 is a Wednesday; day=18 is a Sunday


def cfg(**display):
    return with_defaults({"display": {"language": "en-US", "timezone": "America/Sao_Paulo",
                                      **display}})


def event(start, end, style="solid", busy=True, day=14):
    return Event(at(start, day), at(end, day), "Planning", "Work", style=style, busy=busy)


def all_day_event():
    return Event(at("00:00"), at("00:00", 15), "Conference", "Work", all_day=True)


def snapshot(now="10:20", events=(), day=14, configured="busy"):
    return Snapshot(at(now, day), list(events), [], [], configured=configured)


def test_blocks_are_clipped_to_the_workday_and_all_day_is_left_out():      # Review Focus 4
    snap = snapshot(events=[event("18:30", "20:00", style="striped"), event("07:00", "09:00"),
                            event("10:00", "11:00", busy=False), all_day_event()])
    tl = build_timeline(snap, cfg(workday_start=8, workday_end=19))
    assert (tl.start, tl.end) == (at("08:00"), at("19:00"))
    assert [(b.start.hour, b.start.minute, b.end.hour, b.end.minute) for b in tl.blocks] == \
        [(8, 0, 9, 0), (10, 0, 11, 0), (18, 30, 19, 0)]
    assert [b.style for b in tl.blocks] == ["solid", "solid", "striped"]
    assert [b.busy for b in tl.blocks] == [True, False, True]


def test_an_event_wholly_outside_the_workday_is_dropped():
    snap = snapshot(events=[event("05:00", "06:00"), event("19:00", "20:00"),
                            event("07:00", "08:00")])
    assert build_timeline(snap, cfg(workday_start=8, workday_end=19)).blocks == []


def test_a_workday_ending_at_24_ends_at_the_next_midnight():
    tl = build_timeline(snapshot(events=[event("22:00", "23:30")]),
                        cfg(workday_start=0, workday_end=24))
    assert (tl.start, tl.end) == (at("00:00"), at("00:00", 15)) and len(tl.blocks) == 1


def test_no_timeline_on_a_day_off_or_without_a_busy_calendar():
    assert build_timeline(snapshot(day=18), cfg(workdays=[0, 1, 2, 3, 4])) is None
    assert build_timeline(snapshot(configured="no_busy"), cfg()) is None
    assert build_timeline(snapshot(configured="nothing"), cfg()) is None
    assert build_timeline(snapshot(), cfg()) is not None


def test_no_timeline_while_a_busy_calendar_has_no_data():
    # an empty strip would read as a free day, and nobody knows that
    snap = snapshot(events=[event("10:00", "11:00")])
    snap.unknown = ["Company"]
    assert build_timeline(snap, cfg()) is None


def test_a_timeline_block_never_holds_a_title():
    tl = build_timeline(snapshot(events=[event("10:00", "11:00")]), cfg())
    assert "Planning" not in repr(tl)


def test_next_word_is_the_status_at_the_next_change():
    snap = snapshot(now="10:20", events=[event("10:00", "11:00")])
    t = Translator("en-US")
    assert next_word(snap, cfg(), t, at("11:00")) == t("status.free")
    assert next_word(snapshot(now="09:00", events=[event("10:00", "11:00")]), cfg(), t,
                     at("10:00")) == t("status.busy")
    assert next_word(snap, cfg(), t, None) is None
    assert next_word(snapshot(configured="nothing"), cfg(), t, at("11:00")) is None
    assert snap.now == at("10:20")                                   # the snapshot is not changed
