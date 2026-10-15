"""The admin pages: home, calendars, tasks, screen settings and account.

Every page reads config.toml fresh (``config_edit.read_raw``) and every form carries the digest
of the file as it was read, so a form opened before a hand edit (or in another tab) is refused
with "changed elsewhere" and writes nothing. Saves follow POST/redirect/GET and wake the render
loop. Links never leave the server: pages show ``links.mask``, the link field is always empty,
and "Test" reads the link from the file.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from flask import (Blueprint, abort, current_app, g, jsonify, make_response, redirect,
                   render_template, request)

from .. import check as checker
from .. import config, config_edit, i18n, net
from ..config import DISPLAY_DEFAULTS, SERVER_DEFAULTS, STYLES, is_configured
from ..state import IMAGE_NAME, ServerState
from . import (MAX_PASSWORD_LENGTH, SESSION_COOKIE, SESSION_LIFETIME, add_notice, auth, forms,
               links, translator, wait_text)

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


PASSWORD_MIN = 12
# the keys the screen form owns, and the defaults that are not written when left unchanged
SCREEN_KEYS = [("display", key, DISPLAY_DEFAULTS[key])
               for key in ("language", "timezone", "workday_start", "workday_end", "workdays",
                           "min_gap_minutes")]
SCREEN_KEYS += [("display", "clock", ""), ("server", "refresh_minutes",
                                            SERVER_DEFAULTS["refresh_minutes"])]


@lru_cache(maxsize=1)
def timezones() -> tuple[str, ...]:
    """Time zone names for the screen form, sorted (reading them all takes a moment)."""
    return tuple(sorted(available_timezones()))


def languages() -> list[tuple[str, str]]:
    """(code, name in that language) for every catalog."""
    return [(code, i18n.Translator(code).get("_meta.name") or code) for code in i18n.available()]


def _screen_values(data: dict) -> dict:
    """The screen settings in the file, with defaults, as the form shows them."""
    display = data.get("display", {})
    server = data.get("server", {})
    values = {key: display.get(key, default) for section, key, default in SCREEN_KEYS
              if section == "display"}
    values["language"] = i18n.normalize(str(values["language"]))
    values["clock"] = values["clock"] if values["clock"] in forms.CLOCKS else ""
    days = values["workdays"] if isinstance(values["workdays"], list) else []
    values["workdays"] = [d for d in forms.WEEKDAYS if d in days]
    values["refresh_minutes"] = server.get("refresh_minutes", SERVER_DEFAULTS["refresh_minutes"])
    values["port"] = server.get("port", SERVER_DEFAULTS["port"])
    return values


def _apply_screen(data: dict, values: dict, keep_language: bool) -> None:
    """Writes the form's values into the raw dict, leaving out defaults the file did not have."""
    for section, key, default in SCREEN_KEYS:
        if key == "language" and keep_language:
            continue  # set at startup: never written to the file
        table = data.get(section)
        value = values[key]
        if key == "clock" and value == "":
            if table is not None:
                table.pop("clock", None)
            continue
        if table is not None and key in table:
            table[key] = value
        elif value != default:
            data.setdefault(section, {})[key] = value


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

    def backup_loads() -> bool:
        try:
            data, _ = config.read_toml(state.config_path + config_edit.BACKUP_SUFFIX)
            config_edit.check(data)
        except (config.ConfigMissing, config.ConfigInvalid):
            return False
        return True

    def restore_offer(raw, problem: str | None, warning: str | None) -> str | None:
        """The digest for "Restore previous version", or None when it is not offered: only for
        a broken, invalid or deleted file whose backup would load."""
        if not (problem or warning or (raw is not None and not raw.exists)) or not backup_loads():
            return None
        try:
            return config_edit.digest(config.read_bytes(state.config_path))
        except config.ConfigMissing:
            return config_edit.digest(b"")
        except config.ConfigInvalid:  # e.g. a permission problem: restoring cannot fix it
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
        context["restore"] = restore_offer(raw, problem, context.get("warning"))
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
        context["restore"] = restore_offer(raw, problem, context.get("warning"))
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

    # --- home -------------------------------------------------------------------------------

    def preview_token(last) -> int | None:
        """The ``t`` of the preview's address: the last render time, so a new render shows."""
        try:
            mtime = os.stat(os.path.join(state.output_dir, IMAGE_NAME)).st_mtime_ns // 1_000_000
        except OSError:
            return None  # nothing drawn yet
        return int(last.at.timestamp() * 1000) if last is not None else mtime

    def updated_text(last) -> str | None:
        if last is None:
            return None
        return t()("admin.last_update", date=t().date_short(last.at), time=t().time(last.at))

    @bp.get("/")
    def home():
        last = state.last_render
        raw, problem = read()
        warning = invalid(raw.data) if raw is not None else None
        # from the file as it is now: state.config_problem lags until the next render, so a
        # restore or a first save would otherwise still show the old banner
        missing = raw is not None and not raw.exists
        broken = bool(problem or warning) or (missing and state.config_problem == "broken")
        base = net.admin_url(state.cfg)
        return render_template(
            "home.html", active="home", last=last, updated=updated_text(last),
            preview=preview_token(last), at=last.at.isoformat() if last is not None else "",
            # keep checking for the new screen while a render is pending or none happened yet
            poll=state.render_event.is_set() or last is None,
            kindle_url=base + "/kindle.png" if base else None,
            port=state.cfg["server"]["port"], broken=broken, problem=problem or warning,
            using_defaults=state.using_defaults,
            first_setup=missing and not broken,
            restore=restore_offer(raw, problem, warning))

    @bp.get("/status.json")
    def status():
        last = state.last_render
        return jsonify(at=last.at.isoformat() if last is not None else None,
                       word=last.word if last is not None else None,
                       headline=last.headline if last is not None else None,
                       updated=updated_text(last),
                       errors=list(last.errors) if last is not None else [])

    @bp.post("/render")
    def render_now():
        key = "admin.update_requested" if state.request_render(manual=True) \
            else "admin.update_throttled"
        add_notice(g.session, t()(key))
        return redirect("/", 303)

    @bp.post("/restore")
    def restore():
        try:
            config_edit.restore_backup(state.config_path, request.form.get("digest"))
        except config_edit.ConfigChanged:
            return changed("/")
        except config.ConfigInvalid as ex:
            add_notice(g.session, t()("admin.restore_failed", message=describe(ex)))
            return redirect("/", 303)
        except OSError as ex:
            add_notice(g.session, t()("admin.error_write", error=type(ex).__name__))
            return redirect("/", 303)
        state.request_render()
        add_notice(g.session, t()("admin.restored"))
        return redirect("/", 303)

    # --- screen -------------------------------------------------------------------------------

    def screen_page(raw=None, values=None, errors=None, form_error=None):
        problem = None
        if raw is None:
            raw, problem = read()
        context = {"problem": problem, "active": "screen", "locked": state.language is not None}
        if raw is not None:
            warning = invalid(raw.data)
            current = _screen_values(raw.data)
            context.update(values={**current, **(values or {})}, errors=errors or {},
                           digest=raw.digest, warning=warning, form_error=form_error,
                           languages=languages(), timezones=timezones(),
                           port=current["port"])
        context["restore"] = restore_offer(raw, problem, context.get("warning"))
        if context["locked"]:
            context["locked_name"] = dict(languages()).get(i18n.normalize(state.language),
                                                           state.language)
        return render_template("screen.html", **context)

    @bp.route("/screen", methods=["GET", "POST"])
    def screen():
        if request.method != "POST":
            return screen_page()
        raw, response = fresh("/screen")
        if response:
            return response
        locked = state.language is not None
        values, errors = forms.screen_form(
            request.form, t(), languages=[code for code, _ in languages()],
            timezones=timezones(), language=i18n.normalize(state.language) if locked else None)
        form_error = None
        if not errors:
            data = copy.deepcopy(raw.data)
            _apply_screen(data, values, keep_language=locked)
            response, form_error = save(raw, data, "/screen")
            if response:
                return response
        return screen_page(raw, values, errors, form_error)

    # --- account ------------------------------------------------------------------------------

    def account_page(errors=None, form_error=None, generated=None, status=200):
        body = render_template("account.html", active="account", errors=errors or {},
                               form_error=form_error, generated=generated,
                               min_length=PASSWORD_MIN)
        return make_response(body, status)

    @bp.get("/account")
    def account():
        return account_page()

    @bp.post("/account/password")
    def account_password():
        inkdoor = current_app.extensions["inkdoor"]
        sessions, limiter = inkdoor["sessions"], inkdoor["limiter"]
        password_file = auth.password_path(state.config_path)
        generate = request.form.get("generate") == "1"
        current = request.form.get("current", "")
        new = auth.generate_password() if generate else request.form.get("new", "")
        if not generate:  # checked before scrypt: a refused new password costs nothing
            if len(new) > MAX_PASSWORD_LENGTH:
                return account_page({"new": t()("admin.error_too_long", n=MAX_PASSWORD_LENGTH)})
            if auth.password_length(new) < PASSWORD_MIN:
                return account_page({"new": t()("admin.error_password_short", n=PASSWORD_MIN)})
        encoded = auth.read_password_hash(password_file)
        if encoded is None:  # fail closed, as the login does
            return account_page(form_error=t()("admin.no_password"), status=503)
        ip = request.remote_addr or ""
        wait = limiter.retry_after(ip)  # the login's limit: reserves this attempt, before scrypt
        if wait > 0:
            return account_page(form_error=t()("admin.try_again", wait=wait_text(t(), wait)),
                                status=429)
        ok = False
        try:
            ok = len(current) <= MAX_PASSWORD_LENGTH and auth.verify_password(current, encoded)
        finally:
            (limiter.succeeded if ok else limiter.failed)(ip)
        if not ok:
            return account_page({"current": t()("admin.wrong_current_password")})
        try:
            auth.set_password(password_file, new)
        except OSError as ex:
            return account_page(form_error=t()("admin.error_password_write",
                                               error=type(ex).__name__), status=500)
        # every browser is logged out; this one gets a fresh session. The watcher is told about
        # the new file first, or the next request would see the change and drop that session too
        sessions.drop_all()
        inkdoor["watcher"].changed()
        session = sessions.create()
        g.session = session  # the page below carries the new session's CSRF token
        if generate:  # shown in this response only: never in a redirect, notice or log
            response = account_page(generated=new)
        else:
            add_notice(session, t()("admin.password_changed"))
            response = redirect("/account", 303)
        response.set_cookie(SESSION_COOKIE, session.sid, max_age=SESSION_LIFETIME, path="/",
                            httponly=True, samesite="Strict")
        return response

    return bp
