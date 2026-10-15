"""Admin pages for calendars and tasks: forms, link masking, link tests and secrecy."""
import datetime as dt
import logging
import re
import threading

import pytest

from inkdoor import net, server
from inkdoor.config_edit import read_raw
from inkdoor.i18n import Translator
from inkdoor.sources import SourceCache
from inkdoor.web import links, pages
from test_web_core import BASE, FakeClock, logged_in, make_app, make_state

from conftest import fixture

EN = Translator("en-US")
CANARY = "c4n4ryT0K3Nzz"
LINK = f"https://calendar.example/ical/{CANARY}/private-{CANARY}/basic.ics?k={CANARY}"
TASKS_LINK = f"webcal://tasks.example/pub/{CANARY}/basic.ics?t={CANARY}"
XHR = {"X-Requested-With": "inkdoor"}


@pytest.fixture(autouse=True)
def no_lang_env(monkeypatch):
    monkeypatch.delenv("INKDOOR_LANG", raising=False)


class Admin:
    """A logged-in browser with helpers for the admin forms."""

    def __init__(self, app, state):
        self.app = app
        self.state = state
        self.c = logged_in(app)

    def get(self, path, **kwargs):
        return self.c.get(path, base_url=BASE, **kwargs)

    def post(self, path, data=None, **kwargs):
        return self.c.post(path, base_url=BASE, data=data, **kwargs)

    def digest(self):
        return read_raw(self.state.config_path).digest

    def csrf_data(self, **fields):
        return {"csrf": self.c.csrf, "digest": self.digest(), **fields}

    def form(self, **fields):
        return self.csrf_data(**{"style": "solid", "busy": "1", **fields})

    def raw(self):
        return read_raw(self.state.config_path).data


@pytest.fixture
def state(tmp_path):
    return make_state(tmp_path)


@pytest.fixture
def app(state):
    return make_app(state, FakeClock())


@pytest.fixture
def logged(app, state):
    return Admin(app, state)


def ics(title="Planning", start=None, minutes=30):
    start = start or (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(minutes=minutes)
    fmt = "%Y%m%dT%H%M%SZ"
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:1@test\r\nDTSTART:{start.strftime(fmt)}\r\nDTEND:{end.strftime(fmt)}\r\n"
            f"SUMMARY:{title}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode("utf-8")


def raise_fetch_error(url, **kwargs):
    raise net.FetchError("unreachable")


def body(response):
    return response.get_data(as_text=True)


def add(logged, **fields):
    r = logged.post("/calendars/new", data=logged.form(**fields))
    assert r.status_code == 303, body(r)
    return r


# --- links ------------------------------------------------------------------------------------

def test_mask_shows_host_and_first_segment_only():
    assert links.mask("https://calendar.google.com/calendar/ical/x%40y/private-abc/basic.ics") \
        == "calendar.google.com/calendar/…"
    assert links.mask("https://outlook.office365.com/owa/calendar/a/b/calendar.ics") \
        == "outlook.office365.com/owa/…"
    assert links.mask(LINK) == "calendar.example/ical/…"
    assert links.mask("WEBCAL://Tasks.example/pub/x/basic.ics") == "tasks.example/pub/…"


@pytest.mark.parametrize("url", [
    "https://x.example", "https://x.example/", "https://x.example/?k=secret",
    "https://x.example/secret-token.ics", "https://x.example/secret?k=v",
    "http://x.example#secret",
])
def test_mask_hides_a_single_segment_and_any_query(url):
    assert links.mask(url) == "x.example/…"


def test_mask_drops_user_info_and_keeps_the_port():
    assert links.mask("https://user:s3cretpw@x.example:8443/dav/cal/token/") == "x.example:8443/dav/…"
    assert links.mask("https://[fd00::1]:8443/dav/cal/") == "[fd00::1]:8443/dav/…"
    assert "s3cret" not in links.mask("https://user:s3cret/pw@x.example/dav/cal/")


@pytest.mark.parametrize("url", ["/etc/passwd", "tests/fixtures/work.ics", "file:///x",
                                 "C:\\cal.ics", "", "ftp://x.example/a/b", "https://"])
def test_mask_of_anything_else_is_an_ellipsis(url):
    assert links.mask(url) == "…"


def test_clean_trims_and_lowercases_only_the_scheme():
    assert links.clean("  HTTPS://x.example/a.ics?b=1&c=2\n") == "https://x.example/a.ics?b=1&c=2"
    assert links.clean("WebCal://X.example/A.ics") == "webcal://X.example/A.ics"
    assert links.clean("http://x.example") == "http://x.example"
    assert links.clean("") is None
    assert links.clean(" \t\n") is None


@pytest.mark.parametrize("value", ["/etc/passwd", "file:///x", "ftp://x", "https://",
                                   "http:x.example", "javascript:alert(1)", "x.example/a.ics",
                                   "https://x.example/a b", "https://x.example/\x00",
                                   "https://" + "a" * 5000])
def test_clean_rejects_everything_but_web_links(value):
    with pytest.raises(ValueError):
        links.clean(value)


BAD_HOSTS = [
    "https://cal.example\\SECRETTOKEN/a/b.ics", "https://cal.example;SECRETTOKEN/a/b.ics",
    "https://cal.example:99999/a/b", "https://cal.example:0/a/b", "https://cal.example:/a/b",
    "https://cal.example:8o/a/b", "https://cal_example.test/a/b", "https://-cal.example/a/b",
    "https://cal..example/a/b", "https://kalénder.example/a/b", "https://[fe80::1%25en0]/a/b",
    "https://[cal.example]/a/b", "https://fd00::1/a/b", "https://" + "a" * 64 + ".example/a",
    "https://user@/a/b",
]


@pytest.mark.parametrize("url", BAD_HOSTS)
def test_hosts_a_hostname_cannot_have_are_rejected_and_hidden(url):
    with pytest.raises(ValueError):
        links.clean(url)
    assert links.mask(url) == "…"
    assert not links.is_web(url)


@pytest.mark.parametrize("url, masked", [
    ("https://[FD00::1]:8443/dav/cal/x.ics", "[fd00::1]:8443/dav/…"),
    ("https://[::1]/dav/cal/x.ics", "[::1]/dav/…"),
    ("https://192.168.0.10:5232/radicale/user/cal/", "192.168.0.10:5232/radicale/…"),
    ("https://Cal.Example:65535/a/b?k=1", "cal.example:65535/a/…"),
    ("https://nas/a/b", "nas/a/…"),
    ("https://xn--kalnder-cya.example/a/b", "xn--kalnder-cya.example/a/…"),
    ("https://u:p@cal.example:1/a", "cal.example:1/…"),
])
def test_valid_hosts_and_ports_are_kept_in_the_mask(url, masked):
    assert links.clean(url) == url
    assert links.mask(url) == masked


def test_bad_host_from_the_form_is_a_field_error(logged):
    r = logged.post("/calendars/new",
                    data=logged.form(name="A", url="https://cal.example\\x/a/b.ics"))
    assert r.status_code == 200 and EN("admin.error_link_invalid") in body(r)
    assert logged.raw() == {}


# --- secrets ----------------------------------------------------------------------------------

def test_links_never_leave_the_server(logged, state, caplog, capsys, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr("inkdoor.net.fetch", raise_fetch_error)    # a failing test, too
    add(logged, name="Work", url=LINK)
    r = logged.post("/tasks", data=logged.csrf_data(name="Tasks", url=TASKS_LINK, overdue_days="7"))
    assert r.status_code == 303
    responses = [logged.get(p) for p in ["/", "/calendars", "/calendars/0", "/calendars/new",
                                         "/tasks", "/calendars/9"]]
    responses += [
        logged.post("/calendars/0/test", data=logged.csrf_data()),
        logged.post("/calendars/0/test", data=logged.csrf_data(), headers=XHR),
        logged.post("/tasks/test", data=logged.csrf_data()),
        logged.post("/tasks/test", data=logged.csrf_data(), headers=XHR),
        # a refused form must not echo the pasted link back
        logged.post("/calendars/new", data=logged.form(name="", url=LINK)),
        logged.post("/calendars/0", data=logged.form(name="Work", style="neon", url=LINK)),
        logged.post("/tasks", data=logged.csrf_data(name="T", url=LINK, overdue_days="x")),
    ]
    monkeypatch.setattr("inkdoor.net.fetch", lambda url, **kw: ics())  # and a working one
    responses.append(logged.post("/calendars/0/test", data=logged.csrf_data(), headers=XHR))
    everything = "".join(body(r) + str(r.headers) for r in responses)
    everything += caplog.text + "".join(capsys.readouterr())
    for i in range(len(CANARY) - 7):
        assert CANARY[i:i + 8] not in everything
    assert "calendar.example/ical/…" in body(responses[1])
    assert logged.raw()["calendar"][0]["url"] == LINK
    assert logged.raw()["tasks"]["url"] == TASKS_LINK


# --- calendar forms ---------------------------------------------------------------------------

def test_new_calendar_is_saved_without_defaults_and_wakes_the_render_loop(logged, state):
    r = add(logged, name="Work", url="https://calendar.example/work.ics", status_label="Busy")
    assert r.headers["Location"] == "/calendars"
    assert logged.raw() == {"calendar": [{"name": "Work", "style": "solid", "busy": True,
                                          "status_label": "Busy",
                                          "url": "https://calendar.example/work.ics"}]}
    assert state.render_event.is_set()
    assert EN("admin.saved") in body(logged.get("/calendars"))


def test_link_field_is_empty_with_the_mask_as_placeholder(logged):
    add(logged, name="Work", url=LINK)
    page = body(logged.get("/calendars/0"))
    assert 'type="url"' in page and 'autocomplete="off"' in page
    assert 'placeholder="calendar.example/ical/…"' in page
    assert 'name="url" value=' not in page


def test_empty_link_keeps_the_current_one(logged):
    add(logged, name="Work", url=LINK)
    r = logged.post("/calendars/0", data=logged.form(name="Office", style="striped", url="  "))
    assert r.status_code == 303
    calendar = logged.raw()["calendar"][0]
    assert calendar == {"name": "Office", "style": "striped", "busy": True, "url": LINK}


def test_new_calendar_needs_a_link(logged):
    r = logged.post("/calendars/new", data=logged.form(name="Work", url=""))
    assert r.status_code == 200 and EN("admin.error_link_required") in body(r)
    assert logged.raw() == {}


def test_pasted_link_is_trimmed_and_scheme_case_insensitive(logged):          # Review Focus 2
    add(logged, name="A", url="  HTTPS://x.example/a.ics?b=1&c=2\n")
    assert logged.raw()["calendar"][0]["url"] == "https://x.example/a.ics?b=1&c=2"


@pytest.mark.parametrize("url", ["/etc/passwd", "file:///x", "ftp://x", "tests/fixtures/work.ics"])
def test_file_paths_and_other_schemes_rejected(logged, url):
    add(logged, name="Work", url="https://calendar.example/work.ics")
    before = read_raw(logged.state.config_path)
    r = logged.post("/calendars/new", data=logged.form(name="Other", url=url))
    assert r.status_code == 200
    page = body(r)
    assert EN("admin.error_link_invalid") in page and EN("admin.error_link_repaste") in page
    r = logged.post("/calendars/0", data=logged.form(name="Work", url=url))
    assert r.status_code == 200 and EN("admin.error_link_invalid") in body(r)
    assert read_raw(logged.state.config_path).digest == before.digest


def test_hand_edited_file_path_elsewhere_does_not_block_saves(logged, state):
    path = fixture("work.ics")
    with open(state.config_path, "w", encoding="utf-8") as f:
        f.write(f'[[calendar]]\nname = "Local"\nurl = "{path}"\n')
    add(logged, name="Web", url="https://calendar.example/web.ics")
    calendars = logged.raw()["calendar"]
    assert calendars[0] == {"name": "Local", "url": path}
    assert calendars[1]["url"] == "https://calendar.example/web.ics"
    r = logged.post("/calendars/0", data=logged.form(name="Local", style="outline", url=""))
    assert r.status_code == 303 and logged.raw()["calendar"][0]["url"] == path
    assert "…" in body(logged.get("/calendars"))


def test_hand_edited_file_path_is_not_tested_from_the_admin(logged, state, monkeypatch):
    with open(state.config_path, "w", encoding="utf-8") as f:
        f.write('[[calendar]]\nname = "Local"\nurl = "/etc/passwd"\n')
    monkeypatch.setattr("inkdoor.net.fetch", lambda url, **kw: pytest.fail("fetched"))
    r = logged.post("/calendars/0/test", data=logged.csrf_data(), headers=XHR)
    assert r.status_code == 200 and EN("admin.test_not_web") in body(r)


def test_names_with_special_characters_round_trip_and_are_escaped(logged):    # Review Focus 1
    name = '<b>Empresa "Ltda" & Cia 🎯</b>'
    add(logged, name=name, url=LINK, status_label="Reunião 🎯 'x'")
    assert logged.raw()["calendar"][0]["name"] == name
    assert logged.raw()["calendar"][0]["status_label"] == "Reunião 🎯 'x'"
    page = body(logged.get("/calendars"))
    assert "&lt;b&gt;Empresa &#34;Ltda&#34; &amp; Cia 🎯&lt;/b&gt;" in page
    assert "<b>Empresa" not in page
    assert "&lt;b&gt;Empresa" in body(logged.get("/calendars/0"))


def test_event_titles_in_test_results_are_escaped(logged, monkeypatch):
    add(logged, name="Work", url=LINK)
    monkeypatch.setattr("inkdoor.net.fetch", lambda url, **kw: ics("<script>x()</script> & co"))
    r = logged.post("/calendars/0/test", data=logged.csrf_data(), headers=XHR)
    assert r.status_code == 200 and r.headers["X-Inkdoor-Fragment"] == "1"
    fragment = body(r)
    assert "&lt;script&gt;x()&lt;/script&gt; &amp; co" in fragment and "<script>" not in fragment
    assert "<html" not in fragment and EN("check.events_found", n=1) in fragment


def test_a_test_result_does_not_take_pending_notices(logged, monkeypatch):
    add(logged, name="Work", url=LINK)
    monkeypatch.setattr("inkdoor.net.fetch", raise_fetch_error)
    r = logged.post("/calendars/0/test", data=logged.csrf_data(), headers=XHR)
    assert EN("admin.saved") not in body(r)
    assert EN("admin.saved") in body(logged.get("/calendars"))


def test_form_fields_reference_existing_help_and_errors(logged):
    page = body(logged.post("/calendars/new", data=logged.form(name="", url="")))
    for ids in re.findall(r'aria-describedby="([^"]+)"', page):
        for id_ in ids.split():
            assert f'id="{id_}"' in page, id_


def test_test_without_javascript_shows_the_result_in_the_card(logged, monkeypatch):
    add(logged, name="Work", url=LINK)
    add(logged, name="Home", url="https://calendar.example/home.ics")
    monkeypatch.setattr("inkdoor.net.fetch", raise_fetch_error)
    r = logged.post("/calendars/1/test", data=logged.csrf_data())
    assert r.status_code == 200
    page = body(r)
    assert "<html" in page and page.count('class="test-result') == 1
    unreachable = EN("check.unreachable")
    assert page.index(unreachable[0].upper() + unreachable[1:]) > page.index("Home")


@pytest.mark.parametrize("fields, error, n", [
    ({"style": "neon"}, "admin.error_style", None),
    ({"name": ""}, "admin.error_name_required", None),
    ({"name": "   "}, "admin.error_name_required", None),
    ({"name": "x" * 61}, "admin.error_too_long", 60),
    ({"name": "a\nb"}, "admin.error_single_line", None),
    ({"status_label": "y" * 31}, "admin.error_too_long", 30),
])
def test_tampered_form_values_show_errors(logged, fields, error, n):           # Review Focus 3
    add(logged, name="Work", url=LINK)
    before = logged.digest()
    expected = EN(error, n=n) if n else EN(error)
    for path in ("/calendars/new", "/calendars/0"):
        data = logged.form(**{"name": "Other", "url": "https://calendar.example/o.ics", **fields})
        r = logged.post(path, data=data)
        assert r.status_code == 200, path
        assert expected in body(r) and 'class="field-error"' in body(r)
    assert logged.digest() == before


def test_missing_form_fields_are_errors_not_crashes(logged):
    add(logged, name="Work", url=LINK)
    before = logged.digest()
    for path in ("/calendars/new", "/calendars/0", "/tasks"):
        r = logged.post(path, data=logged.csrf_data())
        assert r.status_code == 200, path
    assert logged.digest() == before


def test_duplicate_names_are_a_field_error(logged):
    add(logged, name="Work", url=LINK)
    add(logged, name="Home", url=LINK)
    r = logged.post("/calendars/1", data=logged.form(name="Work"))
    assert r.status_code == 200
    assert EN("config_error.calendar_duplicate", name="Work").replace("'", "&#39;") in body(r)
    r = logged.post("/calendars/0", data=logged.form(name="Work", style="outline"))
    assert r.status_code == 303     # keeping its own name is fine


def test_unknown_index_redirects_with_a_notice(logged):                        # Review Focus 3
    add(logged, name="Work", url=LINK)
    before = logged.digest()
    r = logged.get("/calendars/99")
    assert r.status_code == 303 and r.headers["Location"] == "/calendars"
    for path in ("/calendars/99", "/calendars/99/delete", "/calendars/99/move",
                 "/calendars/99/test"):
        r = logged.post(path, data=logged.form(name="X", direction="up"))
        assert r.status_code == 303 and r.headers["Location"] == "/calendars", path
    assert logged.digest() == before
    assert EN("admin.changed_elsewhere") in body(logged.get("/calendars"))


def test_stale_digest_is_refused(logged, state):
    add(logged, name="Work", url=LINK)
    stale = logged.form(name="Office")
    with open(state.config_path, "a", encoding="utf-8") as f:
        f.write("\n# edited by hand\n")
    edited = logged.digest()
    for path, extra in [("/calendars/0", {}), ("/calendars/new", {"url": LINK}),
                        ("/calendars/0/delete", {}), ("/calendars/0/move", {"direction": "down"}),
                        ("/tasks", {"url": LINK, "overdue_days": "7"}), ("/tasks/delete", {})]:
        r = logged.post(path, data={**stale, **extra})
        assert r.status_code == 303, path
    for digest in ("", "nothex", "0" * 64):
        r = logged.post("/calendars/0", data={**stale, "digest": digest})
        assert r.status_code == 303
    assert logged.digest() == edited
    assert EN("admin.changed_elsewhere") in body(logged.get("/calendars"))
    r = logged.post("/calendars/0/test", data=stale, headers=XHR)
    assert r.status_code == 409 and EN("admin.changed_elsewhere") in body(r)


def test_move_up_down_and_delete(logged, state):
    for name in ("A", "B", "C"):
        add(logged, name=name, url=f"https://calendar.example/{name}.ics")
    names = lambda: [c["name"] for c in logged.raw()["calendar"]]
    state.render_event.clear()
    r = logged.post("/calendars/2/move", data=logged.csrf_data(direction="up"))
    assert r.status_code == 303 and names() == ["A", "C", "B"] and state.render_event.is_set()
    logged.post("/calendars/0/move", data=logged.csrf_data(direction="down"))
    assert names() == ["C", "A", "B"]
    before = logged.digest()
    logged.post("/calendars/0/move", data=logged.csrf_data(direction="up"))     # already first
    logged.post("/calendars/2/move", data=logged.csrf_data(direction="down"))   # already last
    assert logged.digest() == before
    r = logged.post("/calendars/0/move", data=logged.csrf_data(direction="sideways"))
    assert r.status_code == 400 and logged.digest() == before
    r = logged.post("/calendars/1/delete", data=logged.csrf_data())
    assert r.status_code == 303 and names() == ["C", "B"]
    assert EN("admin.removed") in body(logged.get("/calendars"))


def test_unsafe_actions_need_the_csrf_token(logged):
    add(logged, name="Work", url=LINK)
    before = logged.digest()
    data = logged.form(name="X", direction="down")
    del data["csrf"]
    for path in ("/calendars/0", "/calendars/0/delete", "/calendars/0/move", "/calendars/0/test",
                 "/calendars/new", "/tasks", "/tasks/test", "/tasks/delete"):
        assert logged.post(path, data=data).status_code == 403, path
    assert logged.digest() == before


def test_calendars_page_lists_markers_and_masks(logged):
    add(logged, name="Work", url=LINK, style="striped")
    add(logged, name="Notes", url="https://calendar.example/notes.ics", busy="", style="outline")
    page = body(logged.get("/calendars"))
    assert "marker-striped" in page and "marker-outline" in page
    assert EN("admin.busy_no") in page and EN("admin.busy_yes") in page
    assert 'data-test-target="test-0"' in page and 'data-confirm=' in page
    assert logged.raw()["calendar"][1]["busy"] is False


def test_broken_file_shows_the_error_and_no_forms(logged, state):
    with open(state.config_path, "w", encoding="utf-8") as f:
        f.write("[[calendar]\n")
    for path in ("/calendars", "/tasks"):
        r = logged.get(path)
        assert r.status_code == 200 and "config.toml has a syntax error" in body(r)
        assert 'name="digest"' not in body(r)
    r = logged.post("/calendars/new", data={"csrf": logged.c.csrf, "digest": "0" * 64,
                                            "name": "A", "url": LINK, "style": "solid"})
    assert r.status_code == 303


# --- tasks ------------------------------------------------------------------------------------

def test_tasks_create_edit_and_remove(logged, state):
    page = body(logged.get("/tasks"))
    assert 'value="TickTick"' in page and 'value="7"' in page
    r = logged.post("/tasks", data=logged.csrf_data(name="", url="", overdue_days="7"))
    assert r.status_code == 200 and EN("admin.error_link_required") in body(r)
    r = logged.post("/tasks", data=logged.csrf_data(name="", url=TASKS_LINK, overdue_days="3"))
    assert r.status_code == 303 and state.render_event.is_set()
    assert logged.raw() == {"tasks": {"name": "TickTick", "url": TASKS_LINK, "overdue_days": 3}}
    r = logged.post("/tasks", data=logged.csrf_data(name="Chores", url="", overdue_days="0"))
    assert r.status_code == 303
    assert logged.raw()["tasks"] == {"name": "Chores", "url": TASKS_LINK, "overdue_days": 0}
    assert 'placeholder="tasks.example/pub/…"' in body(logged.get("/tasks"))
    r = logged.post("/tasks/delete", data=logged.csrf_data())
    assert r.status_code == 303 and logged.raw() == {}


@pytest.mark.parametrize("days", ["abc", "-1", "366", "1.5", "", "٣"])
def test_tasks_overdue_days_must_be_a_small_whole_number(logged, days):
    r = logged.post("/tasks", data=logged.csrf_data(url=TASKS_LINK, overdue_days=days))
    assert r.status_code == 200 and EN("admin.error_overdue_days") in body(r)
    assert logged.raw() == {}


def test_tasks_test_shows_the_result(logged, monkeypatch):
    logged.post("/tasks", data=logged.csrf_data(url=TASKS_LINK, overdue_days="7"))
    with open(fixture("tasks.ics"), "rb") as f:
        content = f.read()
    monkeypatch.setattr("inkdoor.net.fetch", lambda url, **kw: content)
    r = logged.post("/tasks/test", data=logged.csrf_data(), headers=XHR)
    assert r.status_code == 200 and "result-ok" in body(r)


def test_tasks_test_without_a_task_list_is_changed_elsewhere(logged):
    r = logged.post("/tasks/test", data=logged.csrf_data())
    assert r.status_code == 303 and r.headers["Location"] == "/tasks"


# --- the door after edits ---------------------------------------------------------------------

def test_removing_last_busy_calendar_never_shows_free(logged, state, monkeypatch):  # Review Focus 4
    monkeypatch.setattr(net, "lan_address", lambda: "192.168.1.20")
    contents = {"work": fixture("work.ics"), "notes": fixture("personal.ics"),
                "tasks": fixture("tasks.ics")}

    def fake_fetch(url, **kwargs):
        name = url.rsplit("/", 1)[1].split(".")[0]
        with open(contents[name], "rb") as f:
            return f.read()

    monkeypatch.setattr("inkdoor.net.fetch", fake_fetch)
    add(logged, name="Work", url="https://calendar.example/work.ics")
    add(logged, name="Notes", url="https://calendar.example/notes.ics", busy="")
    logged.post("/tasks", data=logged.csrf_data(url="https://tasks.example/tasks.ics",
                                                overdue_days="7"))
    server.run_cycle(state, SourceCache())
    assert state.cfg["calendar"][0]["name"] == "Work"

    assert logged.post("/calendars/0/delete", data=logged.csrf_data()).status_code == 303
    server.run_cycle(state, SourceCache())
    assert state.last_render.word == EN("status.unknown")
    assert state.last_render.headline == EN("status.unknown_headline")

    logged.post("/calendars/0/delete", data=logged.csrf_data())
    logged.post("/tasks/delete", data=logged.csrf_data())
    assert logged.raw() == {"calendar": []}
    server.run_cycle(state, SourceCache())
    assert state.last_render.word == EN("status.setup")


# --- concurrency ------------------------------------------------------------------------------

def test_third_concurrent_test_gets_429(app, state, monkeypatch):
    admins = [Admin(app, state) for _ in range(3)]
    add(admins[0], name="Work", url=LINK)
    release, entered, lock = threading.Event(), [], threading.Lock()
    both_in = threading.Event()

    def slow_fetch(url, **kwargs):
        with lock:
            entered.append(url)
            if len(entered) == 2:
                both_in.set()
        release.wait(10)
        raise net.FetchError("timeout")

    monkeypatch.setattr("inkdoor.net.fetch", slow_fetch)
    results = []
    threads = [threading.Thread(target=lambda a=a: results.append(
        a.post("/calendars/0/test", data=a.csrf_data(), headers=XHR).status_code))
        for a in admins[:2]]
    for thread in threads:
        thread.start()
    try:
        assert both_in.wait(10)
        r = admins[2].post("/calendars/0/test", data=admins[2].csrf_data(), headers=XHR)
        assert r.status_code == 429 and EN("admin.test_busy") in body(r)
        r = admins[2].post("/calendars/0/test", data=admins[2].csrf_data())
        assert r.status_code == 429 and EN("admin.test_busy") in body(r) and "<html" in body(r)
    finally:
        release.set()
        for thread in threads:
            thread.join(10)
    assert results == [200, 200]
    assert pages.TESTS.acquire(blocking=False) and pages.TESTS.acquire(blocking=False)
    pages.TESTS.release()
    pages.TESTS.release()


# --- pages in Portuguese ----------------------------------------------------------------------

def test_pages_follow_the_configured_language(tmp_path):
    state = make_state(tmp_path)
    state.cfg["display"]["language"] = "pt-BR"
    admin = Admin(make_app(state, FakeClock()), state)
    pt = Translator("pt-BR")
    assert pt("admin.add_calendar") in body(admin.get("/calendars"))
    assert pt("admin.tasks_title") in body(admin.get("/tasks"))
    r = admin.post("/calendars/new", data=admin.form(name="", url=""))
    assert pt("admin.error_name_required") in body(r)
