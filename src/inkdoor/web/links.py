"""Calendar and task links in the admin: masking for display and checking pasted values.

Links are secrets (anyone with one can read the calendar), so the admin never sends one back to
the browser. Pages show ``mask(url)`` instead, and a pasted link goes through ``clean`` before it
is saved.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

HIDDEN = "…"
MAX_LENGTH = 4096
WEB_SCHEMES = ("http", "https", "webcal")

_WEB = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>.*)\Z", re.DOTALL)
_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f]")


def _web_parts(url) -> tuple[str, str] | None:
    """(scheme, the rest after "://") for an http, https or webcal link with a host, else None."""
    match = _WEB.match(url) if isinstance(url, str) else None
    if match is None or match["scheme"].lower() not in WEB_SCHEMES:
        return None
    try:
        host = urlsplit("http://" + match["rest"]).hostname
    except ValueError:
        return None
    if not host:
        return None
    return match["scheme"].lower(), match["rest"]


def is_web(url) -> bool:
    """True for an http, https or webcal link with a host (in any letter case)."""
    return _web_parts(url) is not None


def mask(url) -> str:
    """The host plus the first path segment, e.g. ``calendar.google.com/calendar/…``.

    The first segment is shown only when more segments follow it, so a link whose only segment is
    the token shows just the host. Never any user info, query string, fragment or later segment.
    Anything that is not a web link (e.g. a local path set by hand) is fully hidden.
    """
    parts = _web_parts(url)
    if parts is None:
        return HIDDEN
    split = urlsplit("http://" + parts[1])
    host = split.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    try:
        port = split.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    segments = split.path.lstrip("/").split("/")
    if len(segments) > 1 and segments[0]:
        return f"{host}/{segments[0]}/{HIDDEN}"
    return f"{host}/{HIDDEN}"


def clean(value: str) -> str | None:
    """A link pasted in the admin, ready to store, or None when the field was left empty.

    Surrounding whitespace is removed and the scheme is lowercased; the rest is kept byte for
    byte. Raises ValueError unless it is an http, https or webcal link: a value without a scheme
    would be read as a local file.
    """
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_LENGTH or _UNSAFE.search(value):
        raise ValueError("not a web link")
    parts = _web_parts(value)
    if parts is None:
        raise ValueError("not a web link")
    return f"{parts[0]}://{parts[1]}"
