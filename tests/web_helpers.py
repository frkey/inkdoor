"""Helpers for the admin app tests: a fake clock, a state with a password, logged-in clients."""
import re

from inkdoor.config import with_defaults
from inkdoor.i18n import Translator
from inkdoor.state import ServerState
from inkdoor.web import auth, create_app

BASE = "http://192.168.0.50:8000"
PASSWORD = "test-pass-not-real-1"
CSP = ("default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
       "form-action 'self'; base-uri 'none'")
EN = Translator("en-US")


class FakeClock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_state(tmp_path, admin_enabled=True, password=PASSWORD, **cfg):
    config_path = tmp_path / "config.toml"
    if password is not None:
        auth.set_password(auth.password_path(str(config_path)), password)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return ServerState(str(config_path), str(out), None,
                       with_defaults({"display": {"language": "en-US"}, **cfg}),
                       None, admin_enabled)


def make_app(state, clock):
    app = create_app(state, clock=clock, monotonic=clock)
    app.testing = True
    app.test_clock = clock  # lets logged_in() step past the one-login-per-second pace
    return app


def client(app, **kwargs):
    return app.test_client(**kwargs)


def cookie(c, name, path="/"):
    return c.get_cookie(name, domain="192.168.0.50", path=path)


def get(c, path, **kwargs):
    return c.get(path, base_url=BASE, **kwargs)


def post(c, path, **kwargs):
    return c.post(path, base_url=BASE, **kwargs)


def login_token(c, path="/login"):
    page = get(c, path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def login(c, password=PASSWORD, next_=None, **kwargs):
    data = {"csrf": login_token(c), "password": password}
    if next_ is not None:
        data["next"] = next_
    return post(c, "/login", data=data, **kwargs)


def logged_in(app):
    app.test_clock.advance(1)
    c = client(app)
    r = login(c)
    assert r.status_code == 302, r.get_data(as_text=True)
    sid = cookie(c, "inkdoor_session").value
    c.csrf = app.extensions["inkdoor"]["sessions"].get(sid).csrf
    return c


# --- builders for what the render loop leaves for Home -------------------------------------------

def day_at(hhmm, day=14):
    """A time on the fixed day the Home tests use (2026-10-14, a Wednesday, in São Paulo)."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    hour, minute = map(int, hhmm.split(":"))                   # "24:00" is the next midnight
    return dt.datetime(2026, 10, day, tzinfo=ZoneInfo("America/Sao_Paulo")) + \
        dt.timedelta(hours=hour, minutes=minute)


def health(name, state, kind="calendar", style="solid", busy=True, items=0, reason=None,
           read_at="10:00"):
    from inkdoor.sources import SourceHealth
    known = state in ("ok", "stale")
    return SourceHealth(kind, name, style if kind == "calendar" else None, busy, state,
                        items if known else 0, day_at(read_at) if known else None,
                        reason if state in ("stale", "failed") else None)


def timeline(start="08:00", end="19:00", blocks=()):
    from inkdoor.dashboard import Block, Timeline
    return Timeline(day_at(start), day_at(end),
                    [Block(day_at(a), day_at(b), style, True) for a, b, style in blocks])


def info(word="In a meeting", headline="until 5:00 PM", sources=(), timeline=None,
         next_word=None, next_change=None, at="10:20"):
    from inkdoor.state import RenderInfo
    return RenderInfo(day_at(at), word, headline, [], next_change, sources=list(sources),
                      timeline=timeline, next_word=next_word)
