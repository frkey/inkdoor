from conftest import at

from inkdoor.sources import collect


def rows(events):
    return [(e.start.strftime("%H:%M"), e.title, e.source) for e in events]


def test_calendars_are_never_merged(cfg):
    snap = collect(cfg, at("12:00"))
    listed = rows(snap.today)
    # the same meeting in two calendars shows up in both
    assert ("13:30", "Roadmap review", "Company") in listed
    # but a repeat inside one calendar collapses into one
    assert sum(1 for _, title, src in listed if src == "Work" and title.lower() == "roadmap review") == 1


def test_windows_time_zone_names(cfg):
    snap = collect(cfg, at("12:00"))
    review = next(e for e in snap.today if e.source == "Work" and "roadmap" in e.title.lower())
    assert review.start.strftime("%H:%M") == "13:30"   # 10:30 in Denver
    assert review.location == ""                        # Teams links are hidden


def test_recurrence_and_cancellations(cfg):
    snap = collect(cfg, at("12:00"))
    assert ("09:00", "Daily", "Work") in rows(snap.today)
    assert ("09:00", "Daily", "Work") in rows(snap.tomorrow)
    assert not any("Old sync" in e.title for e in snap.today)


def test_free_and_all_day_events_do_not_block_the_door(cfg):
    snap = collect(cfg, at("12:00"))
    gym = next(e for e in snap.today if e.title == "Gym")
    birthday = next(e for e in snap.today if e.title == "Birthday")
    assert not gym.busy
    assert birthday.all_day and not birthday.busy


def test_tasks(cfg):
    snap = collect(cfg, at("12:00"))
    assert [t.title for t in snap.tasks] == ["Overdue task", "Call the bank"]
    assert snap.tasks[0].overdue and snap.tasks[0].priority == 3
    assert snap.tasks[1].time.strftime("%H:%M") == "17:00"


def test_unreachable_calendar_is_reported_not_fatal(cfg):
    cfg["calendar"][1]["url"] = "/does/not/exist.ics"
    snap = collect(cfg, at("12:00"))
    assert snap.errors and snap.errors[0].startswith("Company")
    assert snap.today
