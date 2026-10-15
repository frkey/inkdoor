"""Outbound requests and LAN address detection.

Every calendar or task link is fetched through `fetch`, which:

- caps the body (5 MB by default), enforces a total deadline (30 s) and follows at most
  3 redirects, by hand, so every hop can be checked;
- refuses hosts that resolve to loopback, link-local (including the cloud metadata address
  169.254.169.254) or unspecified addresses, on every hop. Private LAN addresses (RFC 1918,
  IPv6 ULA) stay allowed on purpose: a calendar on a LAN Nextcloud or Radicale is a real use,
  so a link can still reach other machines on the LAN. That residual risk is accepted;
- never puts the link in an error. Links are secrets, and `requests` copies the URL path into
  its messages, so every failure becomes a `FetchError` that only carries a short reason, raised
  outside the original handler and `from None` so no chained exception survives.

Known limits, accepted:

- The host is resolved and checked before each request, and `requests` resolves it again to
  connect. A DNS server that answers differently the second time (DNS rebinding) can slip past
  the check.
- The deadline is checked between chunks. Each socket read has its own 10 s timeout, but a
  server that trickles bytes slowly enough can stretch one 64 KB chunk past the deadline.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import requests

REASONS = ("blocked", "too_large", "timeout", "redirects", "http", "unreachable", "bad_link")

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_CHUNK = 65536
_HEADERS = {"User-Agent": "inkdoor"}
_RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_BAD_LINK_ERRORS = (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
                    requests.exceptions.InvalidSchema, requests.exceptions.URLRequired,
                    UnicodeError)


class FetchError(Exception):
    """A link could not be fetched. The message is the reason only, never the link."""

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(f"http {status}" if reason == "http" and status is not None else reason)
        self.reason = reason
        self.status = status


def fetch(url: str, *, max_bytes: int = 5_000_000, deadline: float = 30.0,
          max_redirects: int = 3) -> bytes:
    """Downloads an http(s)/webcal link, or reads a local file when the value has no scheme."""
    try:
        return _fetch(url, max_bytes, deadline, max_redirects)
    except FetchError as ex:
        error = FetchError(ex.reason, ex.status)
    except requests.Timeout:
        error = FetchError("timeout")
    except _BAD_LINK_ERRORS:
        error = FetchError("bad_link")
    except Exception:
        error = FetchError("unreachable")
    # Raised here, outside the handlers, so not even __context__ keeps the original exception
    raise error from None


def _fetch(url: str, max_bytes: int, deadline: float, max_redirects: int) -> bytes:
    started = time.monotonic()
    if not url:
        raise FetchError("bad_link")
    match = _SCHEME.match(url)
    if not match:
        return _read_file(url, max_bytes)        # hand-edited configs and test fixtures
    scheme = match.group(1).lower()
    if scheme == "webcal":
        url = "https" + url[len(scheme):]

    with requests.Session() as session:
        for _ in range(max_redirects + 1):
            host, port = _parse(url)
            _refuse_blocked(host, port)
            _check_deadline(started, deadline)
            response = session.get(url, stream=True, allow_redirects=False, timeout=(5, 10),
                                   headers=_HEADERS)
            with response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["Location"])
                    continue
                if response.status_code >= 400:
                    raise FetchError("http", response.status_code)
                return _read_body(response, started, deadline, max_bytes)
    raise FetchError("redirects")


def _parse(url: str) -> tuple[str, int]:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError("bad_link") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("bad_link")
    return parts.hostname, port or (443 if scheme == "https" else 80)


def _refuse_blocked(host: str, port: int) -> None:
    for *_, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            raise FetchError("blocked")


def _check_deadline(started: float, deadline: float) -> None:
    if time.monotonic() - started > deadline:
        raise FetchError("timeout")


def _read_body(response, started: float, deadline: float, max_bytes: int) -> bytes:
    length = response.headers.get("Content-Length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise FetchError("too_large")
    body = bytearray()
    for chunk in response.iter_content(_CHUNK):
        body += chunk
        if len(body) > max_bytes:
            raise FetchError("too_large")
        _check_deadline(started, deadline)
    return bytes(body)


def _read_file(path: str, max_bytes: int) -> bytes:
    with open(path, "rb") as f:
        content = f.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise FetchError("too_large")
    return content


# ---------------------------------------------------------------- LAN address

def lan_address() -> str | None:
    """Private IPv4 address other devices on the LAN can use to reach this computer."""
    try:
        # A UDP "connect" only picks the route and the source address; no packet is sent
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))
            address = sock.getsockname()[0]
        finally:
            sock.close()
        if _is_private_ipv4(address):
            return address
    except OSError:
        pass
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None)
    except OSError:
        return None
    for *_, sockaddr in infos:
        if _is_private_ipv4(sockaddr[0]):
            return sockaddr[0]
    return None


def _is_private_ipv4(address) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and any(ip in network for network in _RFC1918)
