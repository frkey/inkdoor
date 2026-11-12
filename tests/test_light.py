"""The night light schedule (inkdoor.light): when the Kindle's frontlight should be off."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from inkdoor.light import light_state, next_light_change, parse_time

SP = "America/Sao_Paulo"


def cfg(off="22:00", on="07:00", tz=SP):
    display = {"timezone": tz}
    if off is not None:
        display["light_off"] = off
    if on is not None:
        display["light_on"] = on
    return {"display": display}


def at(y, m, d, h, mi, tz):
    return dt.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz))


@pytest.mark.parametrize("hm, expected", [
    ((21, 59), "on"), ((22, 0), "off"), ((23, 30), "off"), ((0, 0), "off"),
    ((6, 59), "off"), ((7, 0), "on"), ((12, 0), "on"),
])
def test_period_across_midnight(hm, expected):
    assert light_state(at(2026, 11, 11, *hm, SP), cfg()) == expected


@pytest.mark.parametrize("hm, expected", [((12, 59), "on"), ((13, 0), "off"), ((14, 0), "on")])
def test_period_within_a_day(hm, expected):
    assert light_state(at(2026, 11, 11, *hm, SP), cfg("13:00", "14:00")) == expected


def test_seconds_do_not_move_a_boundary():
    late = at(2026, 11, 11, 21, 59, SP).replace(second=59, microsecond=999999)
    assert light_state(late, cfg()) == "on"


def test_not_configured_is_on_with_no_change():
    for c in ({"display": {"timezone": SP}}, cfg(on=None)):
        assert light_state(at(2026, 11, 11, 23, 0, SP), c) == "on"
        assert next_light_change(at(2026, 11, 11, 23, 0, SP), c) is None


def test_state_follows_the_display_time_zone():                      # Review Focus 3
    now = dt.datetime(2026, 11, 12, 1, 30, tzinfo=dt.timezone.utc)   # 22:30 in Sao Paulo
    assert light_state(now, cfg()) == "off"
    assert light_state(now, cfg(tz="Europe/Lisbon")) == "off"        # 01:30 in Lisbon
    assert light_state(now, cfg(tz="Asia/Tokyo")) == "on"            # 10:30 in Tokyo


def test_next_change_today_and_tomorrow():
    assert next_light_change(at(2026, 11, 11, 12, 0, SP), cfg()) == at(2026, 11, 11, 22, 0, SP)
    assert next_light_change(at(2026, 11, 11, 22, 0, SP), cfg()) == at(2026, 11, 12, 7, 0, SP)
    assert next_light_change(at(2026, 11, 11, 23, 0, SP), cfg()) == at(2026, 11, 12, 7, 0, SP)
    assert next_light_change(at(2026, 11, 12, 3, 0, SP), cfg()) == at(2026, 11, 12, 7, 0, SP)


def test_next_change_from_another_zone_is_the_same_instant():
    now = dt.datetime(2026, 11, 11, 15, 0, tzinfo=dt.timezone.utc)   # 12:00 in Sao Paulo
    assert next_light_change(now, cfg()).timestamp() == at(2026, 11, 11, 22, 0, SP).timestamp()


def test_next_change_across_a_daylight_saving_night():
    ny = "America/New_York"                                           # springs forward 2026-03-08
    now = at(2026, 3, 7, 23, 0, ny)
    change = next_light_change(now, cfg(tz=ny))
    assert change == at(2026, 3, 8, 7, 0, ny)
    assert change.timestamp() - now.timestamp() == 7 * 3600          # one hour was skipped


@pytest.mark.parametrize("value", ["7:00", "24:00", "22:60", "22:00:00", "", "22h", 22,
                                   dt.time(22, 0), None, "22:00\n", " 22:00", "２２:００"])
def test_parse_time_refuses_anything_but_hh_mm(value):
    assert parse_time(value) is None


@pytest.mark.parametrize("value, expected", [("00:00", dt.time(0, 0)), ("07:05", dt.time(7, 5)),
                                             ("23:59", dt.time(23, 59))])
def test_parse_time_reads_hh_mm(value, expected):
    assert parse_time(value) == expected
