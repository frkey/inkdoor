"""Loads config.toml and fills in defaults."""
from __future__ import annotations

import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_PATH = "config.toml"
PLACEHOLDER_PREFIX = "PASTE_"

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


def with_defaults(cfg: dict) -> dict:
    cfg.setdefault("display", {})
    cfg.setdefault("server", {})
    for key, value in DISPLAY_DEFAULTS.items():
        cfg["display"].setdefault(key, value)
    for key, value in SERVER_DEFAULTS.items():
        cfg["server"].setdefault(key, value)
    cfg.setdefault("calendar", [])
    return cfg


def load(path: str | None = None) -> dict:
    path = path or os.environ.get("INKDOOR_CONFIG") or DEFAULT_PATH
    if not os.path.exists(path):
        raise ConfigMissing(path)
    with open(path, "rb") as f:
        cfg = with_defaults(tomllib.load(f))
    if os.environ.get("INKDOOR_LANG"):  # set by --lang; wins over the file
        cfg["display"]["language"] = os.environ["INKDOOR_LANG"]
    return cfg


def is_configured(url: str | None) -> bool:
    """True once the user replaced the example placeholder with a real link."""
    return bool(url) and not url.startswith(PLACEHOLDER_PREFIX)
