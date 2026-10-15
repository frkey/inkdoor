import os

import pytest
from conftest import FIXTURES, at

from inkdoor import check, net
from inkdoor.check import check_link, run
from inkdoor.i18n import Translator
from inkdoor.net import FetchError


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_check_output_matches_golden(cfg, capsys, language):
    cfg["display"]["language"] = language
    assert run(cfg, now=at("09:00")) is True
    expected = open(os.path.join(FIXTURES, f"check-golden-{language}.txt"), encoding="utf-8").read()
    assert capsys.readouterr().out == expected


def _ics(tmp_path, name, events):
    """Writes a tiny calendar. events: [(summary, start as YYYYMMDDTHHMMSS local to the display zone)]."""
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:{i}@test\r\nDTSTART;TZID=America/Sao_Paulo:{start}\r\n"
        f"DTEND;TZID=America/Sao_Paulo:{start[:9]}{int(start[9:11]) + 1:02d}{start[11:]}\r\n"
        f"SUMMARY:{summary}\r\nEND:VEVENT\r\n"
        for i, (summary, start) in enumerate(events))
    path = tmp_path / name
    path.write_text("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//inkdoor//tests//EN\r\n"
                    + body + "END:VCALENDAR\r\n", encoding="utf-8")
    return str(path)


def failing_config(cfg, tmp_path):
    """Every failure and warning path of `inkdoor check`, with path-independent output."""
    cfg["calendar"] = [
        {"name": "Placeholder", "url": "PASTE_YOUR_LINK_HERE"},
        {"name": "Unreachable", "url": str(tmp_path / "missing.ics")},
        {"name": "Empty", "url": _ics(tmp_path, "empty.ics", [])},
        {"name": "Busy only", "url": _ics(tmp_path, "busy.ics", [
            ("Busy", "20261014T100000"), ("Tentative", "20261015T100000")])},
        {"name": "Night", "url": _ics(tmp_path, "night.ics", [
            ("Standup", "20261014T020000"), ("Review", "20261014T030000"),
            ("Planning", "20261015T140000")])},
    ]
    cfg["tasks"]["url"] = str(tmp_path / "missing-tasks.ics")
    return cfg


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_check_failures_and_warnings_match_golden(cfg, tmp_path, capsys, language):
    cfg = failing_config(cfg, tmp_path)
    cfg["display"]["language"] = language
    assert run(cfg, now=at("09:00")) is False
    expected = open(os.path.join(FIXTURES, f"check-failures-golden-{language}.txt"), encoding="utf-8").read()
    assert capsys.readouterr().out == expected


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_check_reports_unreadable_sources(cfg, capsys, monkeypatch, language):
    def broken(*args, **kwargs):
        raise ValueError("secret detail")
    monkeypatch.setattr(check, "read_calendar", broken)
    monkeypatch.setattr(check, "read_tasks", broken)
    cfg["display"]["language"] = language
    assert run(cfg, now=at("09:00")) is False
    out = capsys.readouterr().out
    t = Translator(language)
    assert out.count(t("check.read_failed", error="ValueError")) == 4
    assert "secret detail" not in out


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
@pytest.mark.parametrize("error, key, kwargs", [
    (FetchError("http", 401), "check.denied", {"status": 401}),
    (FetchError("http", 403), "check.denied", {"status": 403}),
    (FetchError("http", 404), "check.not_found", {}),
    (FetchError("http", 500), "check.http_error", {"status": 500}),
    (FetchError("blocked"), "check.blocked", {}),
    (FetchError("too_large"), "check.too_large", {"mb": 5}),
    (FetchError("timeout"), "check.timeout", {"seconds": 30}),
    (FetchError("redirects"), "check.redirects", {}),
    (FetchError("bad_link"), "check.bad_link", {}),
    (FetchError("unreachable"), "check.unreachable", {}),
])
def test_check_link_maps_fetch_errors(monkeypatch, language, error, key, kwargs):
    def failing_fetch(url, **kw):
        raise error
    monkeypatch.setattr(check.net, "fetch", failing_fetch)
    t = Translator(language)
    ok, message = check_link("https://cal.example/secret.ics", t)
    assert (ok, message) == (False, t(key, **kwargs))
    assert "{" not in message                             # every placeholder was filled
    for reason in set(net.REASONS) - {"http"}:             # no raw identifiers ("HTTP 403" is fine)
        assert reason not in message.lower()


def test_each_reason_has_its_own_message():
    for language in ["en-US", "pt-BR"]:
        t = Translator(language)
        keys = ["check.blocked", "check.too_large", "check.timeout", "check.redirects",
                "check.bad_link", "check.unreachable"]
        messages = {t(key, mb=5, seconds=30) for key in keys}
        assert len(messages) == len(keys)


def test_check_link_reports_missing_file(tmp_path):
    t = Translator("en-US")
    ok, message = check_link(str(tmp_path / "missing.ics"), t)
    assert (ok, message) == (False, t("check.unreachable"))


def test_check_link_still_inspects_the_content(monkeypatch):
    t = Translator("en-US")
    monkeypatch.setattr(check.net, "fetch", lambda url, **kw: b"<HTML><body>sign in</body></HTML>")
    assert check_link("https://cal.example/x.ics", t) == (False, t("check.html_page"))
    monkeypatch.setattr(check.net, "fetch", lambda url, **kw: b"BEGIN:VCALENDAR\r\nnot really")
    assert check_link("https://cal.example/x.ics", t) == (False, t("check.invalid"))
