import os

import pytest
from conftest import FIXTURES, at

from inkdoor import check
from inkdoor.check import check_link, run
from inkdoor.i18n import Translator
from inkdoor.net import FetchError


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_check_output_matches_golden(cfg, capsys, language):
    cfg["display"]["language"] = language
    assert run(cfg, now=at("09:00")) is True
    expected = open(os.path.join(FIXTURES, f"check-golden-{language}.txt"), encoding="utf-8").read()
    assert capsys.readouterr().out == expected


@pytest.mark.parametrize("error, key, kwargs", [
    (FetchError("http", 401), "check.denied", {"status": 401}),
    (FetchError("http", 403), "check.denied", {"status": 403}),
    (FetchError("http", 404), "check.not_found", {}),
    (FetchError("http", 500), "check.http_error", {"status": 500}),
    (FetchError("blocked"), "check.unreachable", {"error": "blocked"}),
    (FetchError("too_large"), "check.unreachable", {"error": "too_large"}),
])
def test_check_link_maps_fetch_errors(monkeypatch, error, key, kwargs):
    def failing_fetch(url, **kw):
        raise error
    monkeypatch.setattr(check.net, "fetch", failing_fetch)
    t = Translator("en-US")
    assert check_link("https://cal.example/secret.ics", t) == (False, t(key, **kwargs))


def test_check_link_reports_missing_file(tmp_path):
    t = Translator("en-US")
    ok, message = check_link(str(tmp_path / "missing.ics"), t)
    assert (ok, message) == (False, t("check.unreachable", error="unreachable"))


def test_check_link_still_inspects_the_content(monkeypatch):
    t = Translator("en-US")
    monkeypatch.setattr(check.net, "fetch", lambda url, **kw: b"<HTML><body>sign in</body></HTML>")
    assert check_link("https://cal.example/x.ics", t) == (False, t("check.html_page"))
    monkeypatch.setattr(check.net, "fetch", lambda url, **kw: b"BEGIN:VCALENDAR\r\nnot really")
    assert check_link("https://cal.example/x.ics", t) == (False, t("check.invalid"))
