"""The Screen page: the Kindle model, language, time zone, clock, workday and refresh settings."""
from __future__ import annotations

import copy
import datetime as dt
from functools import lru_cache
from zoneinfo import available_timezones

from flask import Blueprint, render_template, request

from .. import i18n
from ..config import DISPLAY_DEFAULTS, SCREENS, SERVER_DEFAULTS
from ..light import parse_time
from ..render import screen_size
from . import forms
from .editing import Editor

# the keys the screen form owns, and the defaults that are not written when left unchanged
SCREEN_KEYS = [("display", key, DISPLAY_DEFAULTS[key])
               for key in ("screen", "language", "timezone", "workday_start", "workday_end",
                           "workdays", "min_gap_minutes")]
SCREEN_KEYS += [("display", "clock", ""), ("server", "refresh_minutes",
                                            SERVER_DEFAULTS["refresh_minutes"])]
# the night light times the form suggests when the file has none; written only when the box is ticked
LIGHT_SUGGESTED = {"light_off": "22:00", "light_on": "07:00"}


@lru_cache(maxsize=1)
def timezones() -> tuple[str, ...]:
    """Time zone names for the screen form, sorted (reading them all takes a moment)."""
    return tuple(sorted(available_timezones()))


def languages() -> list[tuple[str, str]]:
    """(code, name in that language) for every catalog."""
    return [(code, i18n.Translator(code).get("_meta.name") or code) for code in i18n.available()]


def hour_options(t: i18n.Translator, first: int, last: int) -> list[tuple[str, str]]:
    """(value, label) for every whole hour from ``first`` to ``last``; 24 reads as midnight."""
    return [(str(hour), t.time(dt.time(hour % 24))) for hour in range(first, last + 1)]


def light_options(t: i18n.Translator, current) -> list[tuple[str, str]]:
    """(value, label) for every half hour of the day, plus ``current`` when it is a time set by
    hand off that grid (22:45), so the form shows it and a save writes it back unchanged."""
    times = {dt.time(hour, minute) for hour in range(24) for minute in (0, 30)}
    hand_set = parse_time(current)
    if hand_set is not None:
        times.add(hand_set)
    return [(time.strftime("%H:%M"), t.time(time)) for time in sorted(times)]


def choice(t: i18n.Translator, options: list, value) -> tuple[list[tuple[str, str]], str]:
    """(options, the selected value) for a select. When ``value`` is not one of the options (a
    bad value edited by hand, or none) they are led by an empty "Choose", which is the one
    selected: the browser would otherwise show the first option as if it were the setting, and
    a save would quietly write it."""
    if any(option == str(value) for option, _ in options):
        return options, str(value)
    return [("", t("admin.choose"))] + options, ""


def weekday_options(t: i18n.Translator) -> list[tuple[int, str, str]]:
    """(day, short name, full name) for the workday chips, Monday first."""
    short, full = t.get("admin.weekdays_short"), t.get("weekdays")
    return [(day, short[day], full[day]) for day in forms.WEEKDAYS]


def _screen_values(data: dict) -> dict:
    """The screen settings in the file, with defaults, as the form shows them."""
    display = data.get("display", {})
    server = data.get("server", {})
    values = {key: display.get(key, default) for section, key, default in SCREEN_KEYS
              if section == "display"}
    values["language"] = i18n.normalize(str(values["language"]))
    values["clock"] = values["clock"] if values["clock"] in forms.CLOCKS else ""
    values["screen"] = values["screen"] if values["screen"] in SCREENS else DISPLAY_DEFAULTS["screen"]
    days = values["workdays"] if isinstance(values["workdays"], list) else []
    values["workdays"] = [d for d in forms.WEEKDAYS if d in days]
    values["refresh_minutes"] = server.get("refresh_minutes", SERVER_DEFAULTS["refresh_minutes"])
    values["port"] = server.get("port", SERVER_DEFAULTS["port"])
    values["light_enabled"] = all(key in display for key in LIGHT_SUGGESTED)
    for key, suggested in LIGHT_SUGGESTED.items():
        # the suggestion only for a missing key: a bad hand-edited time shows empty, so a save
        # asks for a time instead of quietly writing the suggestion over it
        if key not in display:
            values[key] = suggested
        else:
            values[key] = display[key] if parse_time(display[key]) else ""
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
    display = data.get("display")
    if values["light_enabled"]:
        data.setdefault("display", {}).update({key: values[key] for key in LIGHT_SUGGESTED})
    elif display is not None:
        for key in LIGHT_SUGGESTED:
            display.pop(key, None)


def register(bp: Blueprint, ed: Editor) -> None:
    state, t = ed.state, ed.t

    def screen_page(raw=None, values=None, errors=None, form_error=None):
        problem = None
        if raw is None:
            raw, problem = ed.read()
        context = {"problem": problem, "active": "screen", "locked": state.language is not None}
        if raw is not None:
            warning = ed.invalid(raw.data)
            current = _screen_values(raw.data)
            shown = {**current, **(values or {})}
            if not shown["light_enabled"]:
                # with the switch off the times are not checked (and not posted, once admin.js
                # disabled them): show the file's or the suggested ones, never an empty choice
                shown.update({key: shown[key] or current[key] for key in LIGHT_SUGGESTED})
            selects = {"workday_start": hour_options(t(), 0, 23),
                       "workday_end": hour_options(t(), 1, 24),
                       "light_off": light_options(t(), shown["light_off"]),
                       "light_on": light_options(t(), shown["light_on"])}
            for key, options in selects.items():
                selects[key], shown[key] = choice(t(), options, shown[key])
            last = state.last_render
            context.update(values=shown, errors=errors or {},
                           digest=raw.digest, warning=warning, form_error=form_error,
                           languages=languages(), timezones=timezones(),
                           screens=[(key, *size) for key, size in SCREENS.items()],
                           port=current["port"], start_hours=selects["workday_start"],
                           end_hours=selects["workday_end"],
                           light_off_options=selects["light_off"],
                           light_on_options=selects["light_on"],
                           weekdays=weekday_options(t()),
                           preview=ed.preview_token(), screen_size=screen_size(state.cfg),
                           at=last.at.isoformat() if last is not None else "",
                           poll=ed.watching())
        context["restore"] = ed.restore_offer(raw, problem, context.get("warning"))
        if context["locked"]:
            context["locked_name"] = dict(languages()).get(i18n.normalize(state.language),
                                                           state.language)
        return render_template("screen.html", **context)

    @bp.route("/screen", methods=["GET", "POST"])
    def screen():
        if request.method != "POST":
            return screen_page()
        raw, response = ed.fresh("/screen")
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
            response, form_error = ed.save(raw, data, "/screen")
            if response:
                return response
        return screen_page(raw, values, errors, form_error)
