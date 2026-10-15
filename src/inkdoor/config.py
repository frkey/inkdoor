"""Loads config.toml, fills in defaults and validates it."""
from __future__ import annotations

import os
import sys
from zoneinfo import ZoneInfo

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_PATH = "config.toml"
PLACEHOLDER_PREFIX = "PASTE_"
STYLES = ("solid", "striped", "outline")

DISPLAY_DEFAULTS = {
    "language": "en-US",
    "timezone": "America/Sao_Paulo",
    "workday_start": 8,
    "workday_end": 19,
    "workdays": [0, 1, 2, 3, 4],
    "min_gap_minutes": 30,
}
SERVER_DEFAULTS = {"port": 8000, "refresh_minutes": 5}


class ConfigMissing(Exception):
    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


class ConfigInvalid(Exception):
    """A config value is wrong. ``key`` is a translation key under ``config_error``."""

    def __init__(self, error_key: str, /, **details):
        super().__init__(error_key, details)
        self.key = error_key
        self.details = details


def with_defaults(cfg: dict) -> dict:
    cfg.setdefault("display", {})
    cfg.setdefault("server", {})
    for key, value in DISPLAY_DEFAULTS.items():
        cfg["display"].setdefault(key, value)
    for key, value in SERVER_DEFAULTS.items():
        cfg["server"].setdefault(key, value)
    cfg.setdefault("calendar", [])
    if "tasks" in cfg:
        cfg["tasks"].setdefault("name", "TickTick")
    return cfg


def _is_int(value, low, high) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def validate(cfg: dict) -> dict:
    display, server = cfg["display"], cfg["server"]
    try:
        ZoneInfo(str(display["timezone"]))
    except Exception:
        raise ConfigInvalid("timezone", value=display["timezone"]) from None
    for key in ("workday_start", "workday_end"):
        if not _is_int(display[key], 0, 24):
            raise ConfigInvalid("hour", key=key, value=display[key])
    if not (isinstance(display["workdays"], list) and all(_is_int(d, 0, 6) for d in display["workdays"])):
        raise ConfigInvalid("workdays")
    if display.get("clock") not in (None, "12h", "24h"):
        raise ConfigInvalid("clock", value=display["clock"])
    if not _is_int(server["refresh_minutes"], 1, 1440):
        raise ConfigInvalid("refresh", value=server["refresh_minutes"])
    if not _is_int(server["port"], 1, 65535):
        raise ConfigInvalid("port", value=server["port"])
    names = set()
    for i, calendar in enumerate(cfg["calendar"], start=1):
        name = calendar.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigInvalid("calendar_name", index=i)
        if name in names:
            raise ConfigInvalid("calendar_duplicate", name=name)
        names.add(name)
        if calendar.get("style", "solid") not in STYLES:
            raise ConfigInvalid("style", name=name, value=calendar.get("style"))
    return cfg


def load(path: str | None = None, language: str | None = None) -> dict:
    """Reads and validates the config. ``language`` (from --lang) wins over the file."""
    path = path or os.environ.get("INKDOOR_CONFIG") or DEFAULT_PATH
    if not os.path.exists(path):
        raise ConfigMissing(path)
    with open(path, "rb") as f:
        raw = f.read()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ConfigInvalid("encoding") from None
    except tomllib.TOMLDecodeError as ex:
        raise ConfigInvalid("syntax", error=str(ex)) from None
    for section in ("display", "server", "tasks"):
        if section in data and not isinstance(data[section], dict):
            raise ConfigInvalid("section", section=section)
    if not isinstance(data.get("calendar", []), list) or not all(
            isinstance(c, dict) for c in data.get("calendar", [])):
        raise ConfigInvalid("section", section="calendar")
    cfg = with_defaults(data)
    language = language or os.environ.get("INKDOOR_LANG")
    if language:
        cfg["display"]["language"] = language
    return validate(cfg)


def is_configured(url: str | None) -> bool:
    """True once the user replaced the example placeholder with a real link."""
    return bool(url) and not url.startswith(PLACEHOLDER_PREFIX)
