"""Calendars and tasks pages of the admin.

Every page reads config.toml fresh (``config_edit.read_raw``) and every form carries the digest
of the file as it was read, so a form opened before a hand edit (or in another tab) is refused
with "changed elsewhere" and writes nothing. Saves follow POST/redirect/GET and wake the render
loop. Links never leave the server: pages show ``links.mask``, the link field is always empty,
and "Test" reads the link from the file.
"""
from __future__ import annotations

import copy
import datetime as dt
import threading
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, g, make_response, redirect, render_template, request

from .. import check as checker
from .. import config, config_edit
from ..config import STYLES, is_configured
from ..state import ServerState
from . import add_notice, forms, links, translator

# At most two link tests at a time across all browsers; a third gets "busy" (429) at once, so
# slow links can never take all of Waitress's threads away from /kindle.png.
TESTS = threading.BoundedSemaphore(2)
FRAGMENT_HEADER = "X-Inkdoor-Fragment"  # tells admin.js the answer is a result, not a full page


@dataclass
class TestResult:
    index: int | None                        # the tested calendar; None for the task list
    rows: list = field(default_factory=list)  # {"kind": "line"|"event", "level"|"when", "text"}
    message: str | None = None               # instead of rows: busy, not testable...
    level: str = "fail"


def _masked(url) -> str | None:
    """The link as pages may show it, or None when there is no link yet."""
    return links.mask(url) if isinstance(url, str) and is_configured(url) else None


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _calendar_entry(values: dict, link: str | None, old: dict) -> dict:
    """The calendar as written to the file: known keys first, unknown keys kept."""
    entry = {"name": values["name"], "style": values["style"], "busy": values["busy"]}
    if values["status_label"]:
        entry["status_label"] = values["status_label"]
    url = link or old.get("url")
    if url is not None:
        entry["url"] = url
    entry.update((k, v) for k, v in old.items() if k not in entry and k != "status_label")
    return entry


def blueprint(state: ServerState) -> Blueprint:
    bp = Blueprint("pages", __name__)

    def t():
        if "t" not in g:
            g.t = translator(state)
        return g.t

    def describe(ex: config.ConfigInvalid) -> str:
        return t()(f"config_error.{ex.key}", **ex.details)

    def read():
        """(raw, None), or (None, the translated reason the file cannot be read)."""
        try:
            return config_edit.read_raw(state.config_path), None
        except config.ConfigInvalid as ex:
            return None, describe(ex)

    def invalid(data: dict) -> str | None:
        try:
            config_edit.check(data)
        except config.ConfigInvalid as ex:
            return describe(ex)
        return None

    def changed(target: str):
        add_notice(g.session, t()("admin.changed_elsewhere"))
        return redirect(target, 303)

    def fresh(target: str):
        """(raw, None) when the form was made from the file as it is now, else (None, redirect)."""
        raw, _ = read()
        if raw is None:
            return None, redirect(target, 303)  # the page explains what is wrong with the file
        if request.form.get("digest") != raw.digest:
            return None, changed(target)
        return raw, None

    def save(raw, data: dict, target: str, notice: str = "admin.saved"):
        """(redirect, None) after a save, or (None, a translated reason nothing was written)."""
        try:
            config_edit.save(state.config_path, data, raw.digest)
        except config_edit.ConfigChanged:
            return changed(target), None
        except config.ConfigInvalid as ex:
            return None, t()("admin.error_config", message=describe(ex))
        except OSError as ex:
            return None, t()("admin.error_write", error=type(ex).__name__)
        state.request_render()
        add_notice(g.session, t()(notice))
        return redirect(target, 303), None

    def save_action(raw, data: dict, target: str, notice: str):
        """Saves a form without fields (remove, move): a refusal becomes a notice."""
        response, error = save(raw, data, target, notice)
        if response is None:
            add_notice(g.session, error)
            response = redirect(target, 303)
        return response

    def link_given() -> bool:
        value = request.form.get("url", "")
        return isinstance(value, str) and bool(value.strip())

    # --- link tests ---------------------------------------------------------------------------

    def is_xhr() -> bool:
        return request.headers.get("X-Requested-With") == "inkdoor"

    def fragment(result: TestResult, status: int):
        response = make_response(render_template("_test_result.html", result=result), status)
        response.headers[FRAGMENT_HEADER] = "1"
        return response

    def test_config(raw) -> dict:
        """The file's settings with defaults, in the language and clock of the admin pages."""
        try:
            cfg = config_edit.check(raw.data)
        except config.ConfigInvalid:  # e.g. a bad time zone: test with what the door uses
            cfg = copy.deepcopy(state.cfg)
        cfg["display"]["language"] = t().language
        cfg["display"]["clock"] = t().clock
        return cfg

    def report_rows(report: checker.SourceReport) -> list:
        lines = [{"kind": "line", "level": level, "text": _capitalized(text)}
                 for level, text in report.lines]
        events = [{"kind": "event", "text": title,
                   "when": f"{t().date_short(start)} {t().time(start)}" if start else ""}
                  for start, title in report.upcoming]
        at = len(lines) if report.upcoming_at is None else report.upcoming_at
        return lines[:at] + events + lines[at:]

    def run_test(index: int | None, source: dict, raw, check):
        """(result, status) of testing one calendar or task list taken from the raw file."""
        source = dict(source)
        url = source.get("url")
        source["url"] = url if isinstance(url, str) else ""
        source["name"] = str(source.get("name", forms.DEFAULT_TASKS_NAME))
        if is_configured(source["url"]) and not links.is_web(source["url"]):
            # a local path set by hand: the admin never reads local files
            return TestResult(index, message=t()("admin.test_not_web"), level="warn"), 200
        if not TESTS.acquire(blocking=False):
            return TestResult(index, message=t()("admin.test_busy"), level="warn"), 429
        try:
            cfg = test_config(raw)
            now = dt.datetime.now(ZoneInfo(cfg["display"]["timezone"]))
            report = check(source, cfg, now)
        finally:
            TESTS.release()
        return TestResult(index, rows=report_rows(report)), 200

    def test_refused(target: str, problem: str | None):
        if is_xhr():
            message = problem or t()("admin.changed_elsewhere")
            return fragment(TestResult(None, message=message), 409)
        return redirect(target, 303) if problem else changed(target)

    # --- calendars ----------------------------------------------------------------------------

    def calendar_cards(raw) -> list:
        cards = []
        for index, calendar in enumerate(raw.data.get("calendar", [])):
            style = calendar.get("style", "solid")
            cards.append({
                "index": index, "name": str(calendar.get("name", "")),
                "style": style if style in STYLES else "solid",
                "busy": bool(calendar.get("busy", True)),
                "status_label": str(calendar.get("status_label") or ""),
                "link": _masked(calendar.get("url")),
            })
        return cards

    def calendars_page(raw=None, result: TestResult | None = None, status: int = 200):
        problem = None
        if raw is None:
            raw, problem = read()
        context = {"problem": problem, "result": result, "default_label": t()("status.busy")}
        if raw is not None:
            context.update(cards=calendar_cards(raw), digest=raw.digest, warning=invalid(raw.data))
        return render_template("calendars.html", **context), status

    def calendar_form_page(raw, index, values, errors=None, form_error=None):
        old = raw.data["calendar"][index] if index is not None else {}
        return render_template(
            "calendar_form.html", index=index, values=values, errors=errors or {},
            link=_masked(old.get("url")), digest=raw.digest, styles=STYLES,
            repaste=bool(errors) and link_given(), form_error=form_error,
            default_label=t()("status.busy"))

    def calendar_values(calendar: dict) -> dict:
        return {"name": str(calendar.get("name", "")), "style": calendar.get("style", "solid"),
                "busy": bool(calendar.get("busy", True)),
                "status_label": str(calendar.get("status_label") or "")}

    @bp.get("/calendars")
    def calendars():
        return calendars_page()

    @bp.route("/calendars/new", methods=["GET", "POST"])
    def calendar_new():
        if request.method != "POST":
            raw, _ = read()
            if raw is None:
                return redirect("/calendars", 303)
            return calendar_form_page(raw, None, calendar_values({}))
        raw, response = fresh("/calendars")
        if response:
            return response
        data = copy.deepcopy(raw.data)
        existing = data.get("calendar", [])
        values, link, errors = forms.calendar_form(
            request.form, t(), other_names=[c.get("name") for c in existing], new=True)
        form_error = None
        if not errors:
            data["calendar"] = existing + [_calendar_entry(values, link, {})]
            response, form_error = save(raw, data, "/calendars")
            if response:
                return response
        return calendar_form_page(raw, None, values, errors, form_error)

    @bp.route("/calendars/<int:index>", methods=["GET", "POST"])
    def calendar_edit(index: int):
        if request.method != "POST":
            raw, _ = read()
            if raw is None:
                return redirect("/calendars", 303)
            existing = raw.data.get("calendar", [])
            if index >= len(existing):
                return changed("/calendars")
            return calendar_form_page(raw, index, calendar_values(existing[index]))
        raw, response = fresh("/calendars")
        if response:
            return response
        data = copy.deepcopy(raw.data)
        existing = data.get("calendar", [])
        if index >= len(existing):
            return changed("/calendars")
        others = [c.get("name") for i, c in enumerate(existing) if i != index]
        values, link, errors = forms.calendar_form(request.form, t(), other_names=others,
                                                   new=False)
        form_error = None
        if not errors:
            existing[index] = _calendar_entry(values, link, existing[index])
            response, form_error = save(raw, data, "/calendars")
            if response:
                return response
        return calendar_form_page(raw, index, values, errors, form_error)

    @bp.post("/calendars/<int:index>/delete")
    def calendar_delete(index: int):
        raw, response = fresh("/calendars")
        if response:
            return response
        data = copy.deepcopy(raw.data)
        existing = data.get("calendar", [])
        if index >= len(existing):
            return changed("/calendars")
        del existing[index]
        return save_action(raw, data, "/calendars", "admin.removed")

    @bp.post("/calendars/<int:index>/move")
    def calendar_move(index: int):
        raw, response = fresh("/calendars")
        if response:
            return response
        data = copy.deepcopy(raw.data)
        existing = data.get("calendar", [])
        if index >= len(existing):
            return changed("/calendars")
        direction = request.form.get("direction")
        if direction not in ("up", "down"):
            abort(400)
        other = index - 1 if direction == "up" else index + 1
        if not 0 <= other < len(existing):
            return redirect("/calendars", 303)  # already first or last: nothing to do
        existing[index], existing[other] = existing[other], existing[index]
        return save_action(raw, data, "/calendars", "admin.saved")

    @bp.post("/calendars/<int:index>/test")
    def calendar_test(index: int):
        raw, problem = read()
        existing = raw.data.get("calendar", []) if raw is not None else []
        if raw is None or request.form.get("digest") != raw.digest or index >= len(existing):
            return test_refused("/calendars", problem)
        result, status = run_test(index, existing[index], raw, checker.check_calendar)
        if is_xhr():
            return fragment(result, status)
        return calendars_page(raw, result, status)

    # --- tasks --------------------------------------------------------------------------------

    def tasks_values(section: dict) -> dict:
        return {"name": str(section.get("name", forms.DEFAULT_TASKS_NAME)),
                "overdue_days": section.get("overdue_days", forms.DEFAULT_OVERDUE)}

    def tasks_page(raw=None, values=None, errors=None, form_error=None,
                   result: TestResult | None = None, status: int = 200):
        problem = None
        if raw is None:
            raw, problem = read()
        context = {"problem": problem, "result": result}
        if raw is not None:
            section = raw.data.get("tasks")
            context.update(
                exists=section is not None, link=_masked((section or {}).get("url")),
                name=str((section or {}).get("name", forms.DEFAULT_TASKS_NAME)),
                values=values or tasks_values(section or {}), errors=errors or {},
                digest=raw.digest, warning=invalid(raw.data), form_error=form_error,
                repaste=bool(errors) and link_given())
        return render_template("tasks.html", **context), status

    @bp.route("/tasks", methods=["GET", "POST"])
    def tasks():
        if request.method != "POST":
            return tasks_page()
        raw, response = fresh("/tasks")
        if response:
            return response
        data = copy.deepcopy(raw.data)
        old = data.get("tasks")
        values, link, errors = forms.tasks_form(request.form, t(), new=old is None)
        form_error = None
        if not errors:
            old = old or {}
            entry = {"name": values["name"]}
            url = link or old.get("url")
            if url is not None:
                entry["url"] = url
            entry["overdue_days"] = values["overdue_days"]
            entry.update((k, v) for k, v in old.items() if k not in entry)
            data["tasks"] = entry
            response, form_error = save(raw, data, "/tasks")
            if response:
                return response
        return tasks_page(raw, values, errors, form_error)

    @bp.post("/tasks/delete")
    def tasks_delete():
        raw, response = fresh("/tasks")
        if response:
            return response
        data = copy.deepcopy(raw.data)
        if "tasks" not in data:
            return redirect("/tasks", 303)
        del data["tasks"]
        return save_action(raw, data, "/tasks", "admin.removed")

    @bp.post("/tasks/test")
    def tasks_test():
        raw, problem = read()
        section = raw.data.get("tasks") if raw is not None else None
        if raw is None or request.form.get("digest") != raw.digest or section is None:
            return test_refused("/tasks", problem)
        result, status = run_test(None, section, raw, checker.check_tasks)
        if is_xhr():
            return fragment(result, status)
        return tasks_page(raw, result=result, status=status)

    return bp
