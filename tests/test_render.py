import pytest
from conftest import at

from inkdoor.config import with_defaults
from inkdoor.demo import demo_config, demo_snapshot
from inkdoor.i18n import Translator
from inkdoor.render import (H, W, compute_status, render, render_error, render_host_rejected,
                            render_setup, translator_for)
from inkdoor.sources import Snapshot, collect

KINDLE_GRAYS = {i * 17 for i in range(16)}


def grays(img):
    return {v for v, count in enumerate(img.histogram()) if count}


def test_status_in_meeting_and_free(cfg):
    t = Translator("en-US")
    st = compute_status(collect(cfg, at("13:45")), cfg, t)
    assert st.busy and st.word == "In a meeting" and st.headline == "until 2:30 PM"

    st = compute_status(collect(cfg, at("10:00")), cfg, t)
    assert not st.busy and st.word == "Free" and st.headline == "until 1:30 PM"


def test_status_in_portuguese(cfg):
    t = Translator("pt-BR")
    st = compute_status(collect(cfg, at("13:45")), cfg, t)
    assert st.word == "Em reunião" and st.headline == "até 14:30"


def test_custom_status_label_wins(cfg):
    snap = collect(cfg, at("13:45"))
    for e in snap.today:
        e.status_label = "On a call"
    assert compute_status(snap, cfg, Translator("pt-BR")).word == "On a call"


def test_after_hours(cfg):
    st = compute_status(collect(cfg, at("21:30")), cfg, Translator("en-US"))
    assert not st.busy and st.headline == "after hours"


def test_never_free_when_a_busy_calendar_is_unreadable(cfg):
    cfg["calendar"][0]["url"] = "/does/not/exist.ics"   # Work fails, no cache
    st = compute_status(collect(cfg, at("10:00")), cfg, Translator("en-US"))
    assert st.busy and st.word == "Knock first" and "Work" in st.detail


def test_workday_end_24_is_accepted(cfg):
    cfg["display"]["workday_end"] = 24
    assert render(collect(cfg, at("23:30")), cfg).size == (W, H)


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
@pytest.mark.parametrize("hour", ["7:30", "10:20", "15:20", "16:50", "21:10"])
def test_demo_renders_at_kindle_size(language, hour):
    cfg = demo_config(language)
    img = render(demo_snapshot(cfg, hour), cfg)
    assert img.size == (W, H) == (1072, 1448)
    assert img.mode == "L"
    assert grays(img) <= KINDLE_GRAYS


def test_long_labels_and_many_calendars_do_not_break_the_layout():
    cfg = demo_config("pt-BR")
    cfg["calendar"] += [{"name": f"Calendar number {i}", "style": "solid"} for i in range(5)]
    snap = demo_snapshot(cfg, "10:20")
    for e in snap.today:
        e.status_label = "Não perturbe, em ligação muito importante com o cliente"
    st = compute_status(snap, cfg, Translator("pt-BR"))
    assert st.word.startswith("Não perturbe")
    assert render(snap, cfg).size == (W, H)


def test_empty_day():
    cfg = with_defaults({"display": {"language": "en-US"}})
    snap = Snapshot(at("10:00"), [], [], [], [])
    assert grays(render(snap, cfg)) <= KINDLE_GRAYS


def test_error_screen():
    img = render_error(None, "ValueError: something went wrong " * 10)
    assert img.size == (W, H) and grays(img) <= KINDLE_GRAYS


def test_no_busy_never_says_free(cfg):
    snap = Snapshot(at("10:00"), [], [], [], configured="no_busy")
    st = compute_status(snap, cfg, translator_for(cfg))
    assert st.busy and st.word == "Knock first"


def test_setup_and_host_screens_use_kindle_grays(cfg):
    for img in [render_setup(cfg, "http://192.168.100.200:65535"), render_setup(cfg, None),
                render_host_rejected(cfg, "door.example.com")]:
        assert img.size == (1072, 1448) and grays(img) <= KINDLE_GRAYS
