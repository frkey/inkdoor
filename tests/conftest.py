import datetime as dt
import os
from zoneinfo import ZoneInfo

import pytest

from inkdoor.config import with_defaults

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
TZ = ZoneInfo("America/Sao_Paulo")


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


@pytest.fixture
def cfg():
    path = lambda name: os.path.join(FIXTURES, name)
    return with_defaults({
        "display": {"language": "en-US", "timezone": "America/Sao_Paulo"},
        "calendar": [
            {"name": "Work", "style": "solid", "busy": True, "url": path("work.ics")},
            {"name": "Company", "style": "striped", "busy": True, "url": path("company.ics")},
            {"name": "Personal", "style": "outline", "busy": True, "status_label": "Busy",
             "url": path("personal.ics")},
        ],
        "tasks": {"name": "TickTick", "url": path("tasks.ics"), "overdue_days": 7},
    })


def at(hhmm: str, day: int = 14) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 10, day, h, m, tzinfo=TZ)
