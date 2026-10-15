"""Reads and checks the calendar and task forms of the admin.

Every value comes from a browser and may be missing or tampered with: the readers never raise,
they return the cleaned values plus a dict of translated errors keyed by field name. A pasted
link is never put back into the values, so a refused form cannot echo it to the browser.
"""
from __future__ import annotations

import unicodedata

from ..config import STYLES
from ..i18n import Translator
from . import links

NAME_MAX = 60
LABEL_MAX = 30
OVERDUE_MAX = 365
DEFAULT_OVERDUE = 7
DEFAULT_TASKS_NAME = "TickTick"


def _text(form, key: str) -> str:
    value = form.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _check_text(value: str, limit: int, t: Translator) -> str | None:
    if any(unicodedata.category(c) == "Cc" for c in value):
        return t("admin.error_single_line")
    if len(value) > limit:
        return t("admin.error_too_long", n=limit)
    return None


def _name(form, key: str, errors: dict, t: Translator, default: str | None = None) -> str:
    name = _text(form, key) or (default or "")
    problem = t("admin.error_name_required") if not name else _check_text(name, NAME_MAX, t)
    if problem:
        errors[key] = problem
    return name


def _link(form, errors: dict, t: Translator, required: bool) -> str | None:
    """The cleaned link, or None to keep the current one (or on error)."""
    try:
        link = links.clean(form.get("url", "") if isinstance(form.get("url"), str) else "")
    except ValueError:
        errors["url"] = t("admin.error_link_invalid")
        return None
    if link is None and required:
        errors["url"] = t("admin.error_link_required")
    return link


def calendar_form(form, t: Translator, *, other_names: list, new: bool):
    """(values, link, errors) for the calendar form. ``link`` None means keep the current one."""
    errors: dict[str, str] = {}
    name = _name(form, "name", errors, t)
    if "name" not in errors and name in other_names:
        errors["name"] = t("config_error.calendar_duplicate", name=name)
    style = _text(form, "style")
    if style not in STYLES:
        errors["style"] = t("admin.error_style")
    label = _text(form, "status_label")
    problem = _check_text(label, LABEL_MAX, t)
    if problem:
        errors["status_label"] = problem
    values = {"name": name, "style": style, "busy": bool(form.get("busy")),
              "status_label": label}
    link = _link(form, errors, t, required=new)
    return values, link, errors


def tasks_form(form, t: Translator, *, new: bool):
    """(values, link, errors) for the task list form. ``link`` None means keep the current one."""
    errors: dict[str, str] = {}
    name = _name(form, "name", errors, t, default=DEFAULT_TASKS_NAME)
    raw_days = _text(form, "overdue_days")
    days = None
    if (len(raw_days) <= 3 and raw_days.isascii() and raw_days.isdigit()
            and int(raw_days) <= OVERDUE_MAX):
        days = int(raw_days)
    else:
        errors["overdue_days"] = t("admin.error_overdue_days")
    values = {"name": name, "overdue_days": days if days is not None else raw_days}
    link = _link(form, errors, t, required=new)
    return values, link, errors
