import pytest
from conftest import at

from inkdoor.demo import demo_config, demo_snapshot
from inkdoor.i18n import Translator
from inkdoor.render import H, W, compute_status, render
from inkdoor.sources import collect


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


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
@pytest.mark.parametrize("hour", ["7:30", "10:20", "15:20", "16:50", "21:10"])
def test_demo_renders_at_kindle_size(language, hour):
    cfg = demo_config(language)
    img = render(demo_snapshot(cfg, hour), cfg)
    assert img.size == (W, H) == (1072, 1448)
    assert img.mode == "L"
    shades = {v for v, count in enumerate(img.histogram()) if count}
    assert shades <= {i * 17 for i in range(16)}   # only the 16 grays the Kindle shows
