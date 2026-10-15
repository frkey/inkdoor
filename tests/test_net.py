import io
import socket

import pytest
import requests

from inkdoor import net
from inkdoor.net import FetchError, fetch, lan_address


# ------------------------------------------------------------ helpers (no network)

def resolve_to(monkeypatch, ip_or_map):
    """Makes every host resolve to one IP, or each host to its own IP when given a dict."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = ip_or_map.get(host, "203.0.113.10") if isinstance(ip_or_map, dict) else ip_or_map
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
    monkeypatch.setattr(net.socket, "getaddrinfo", fake_getaddrinfo)


def make_response(status, body=b"", headers=None, raw=None):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response.raw = raw if raw is not None else io.BytesIO(body)
    return response


def respond_sequence(monkeypatch, *responses):
    """Session.get returns the given responses in order and records the requested URLs."""
    calls = []
    queue = list(responses)

    def fake_get(self, url, **kwargs):
        calls.append((url, kwargs))
        return queue.pop(0)
    monkeypatch.setattr(requests.Session, "get", fake_get)
    return calls


def respond(monkeypatch, status, body=b"", headers=None):
    return respond_sequence(monkeypatch, make_response(status, body, headers))


def respond_raises(monkeypatch, exc):
    def fake_get(self, url, **kwargs):
        raise exc
    monkeypatch.setattr(requests.Session, "get", fake_get)


def redirect(location, status=302):
    return make_response(status, headers={"Location": location})


# ------------------------------------------------------------ address checks

def test_refuses_loopback_and_link_local(monkeypatch):
    for ip in ["127.0.0.1", "::1", "169.254.169.254", "0.0.0.0", "fe80::1", "::ffff:127.0.0.1"]:
        resolve_to(monkeypatch, ip)
        with pytest.raises(FetchError) as e:
            fetch("https://cal.example/x.ics")
        assert e.value.reason == "blocked"
        assert e.value.status is None
        assert str(e.value) == "blocked"


def test_allows_private_lan(monkeypatch):
    resolve_to(monkeypatch, "192.168.1.20")
    respond(monkeypatch, 200, b"BEGIN:VCALENDAR")
    assert fetch("https://nextcloud.lan/x.ics").startswith(b"BEGIN")


def test_allows_unique_local_ipv6(monkeypatch):
    resolve_to(monkeypatch, "fd12:3456:789a::5")
    respond(monkeypatch, 200, b"BEGIN:VCALENDAR")
    assert fetch("https://radicale.lan/x.ics") == b"BEGIN:VCALENDAR"


def test_request_options(monkeypatch):
    resolve_to(monkeypatch, "203.0.113.10")
    calls = respond(monkeypatch, 200, b"BEGIN:VCALENDAR")
    fetch("https://cal.example/x.ics")
    (url, kwargs), = calls
    assert url == "https://cal.example/x.ics"
    assert kwargs["stream"] is True
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (5, 10)
    assert kwargs["headers"] == {"User-Agent": "inkdoor"}


# ------------------------------------------------------------ redirects

def test_follows_redirects_and_checks_every_hop(monkeypatch):
    resolve_to(monkeypatch, "203.0.113.10")
    calls = respond_sequence(monkeypatch,
                             redirect("https://cdn.example/a.ics"),
                             redirect("/b.ics", status=301),
                             redirect("c.ics", status=307),
                             make_response(200, b"BEGIN:VCALENDAR"))
    assert fetch("https://cal.example/x.ics") == b"BEGIN:VCALENDAR"
    assert [url for url, _ in calls] == ["https://cal.example/x.ics", "https://cdn.example/a.ics",
                                         "https://cdn.example/b.ics", "https://cdn.example/c.ics"]


def test_blocked_on_redirect_hop(monkeypatch):      # public → 302 → 127.0.0.1
    resolve_to(monkeypatch, {"cal.example": "203.0.113.10", "evil.example": "127.0.0.1",
                             "127.0.0.1": "127.0.0.1"})
    for target in ["http://127.0.0.1/admin", "https://evil.example/x.ics"]:
        calls = respond_sequence(monkeypatch, redirect(target), make_response(200, b"secret"))
        with pytest.raises(FetchError) as e:
            fetch("https://cal.example/x.ics")
        assert e.value.reason == "blocked"
        assert len(calls) == 1          # the blocked hop was never requested


def test_redirect_to_other_scheme_is_bad_link(monkeypatch):
    resolve_to(monkeypatch, "203.0.113.10")
    respond_sequence(monkeypatch, redirect("file:///etc/passwd"))
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "bad_link"


def test_redirect_limit(monkeypatch):               # 4 redirects → reason "redirects"
    resolve_to(monkeypatch, "203.0.113.10")
    calls = respond_sequence(monkeypatch, *[redirect(f"https://cal.example/{i}") for i in range(4)],
                             make_response(200, b"BEGIN:VCALENDAR"))
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "redirects"
    assert len(calls) == 4


# ------------------------------------------------------------ size and time

def test_size_cap(monkeypatch):                     # streamed 6 MB → reason "too_large"
    resolve_to(monkeypatch, "203.0.113.10")
    respond(monkeypatch, 200, b"x" * 6_000_000)
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "too_large"


def test_size_cap_from_content_length(monkeypatch):
    resolve_to(monkeypatch, "203.0.113.10")
    respond(monkeypatch, 200, b"BEGIN:VCALENDAR", headers={"Content-Length": "6000000"})
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "too_large"


def test_body_at_the_cap_is_accepted(monkeypatch):
    resolve_to(monkeypatch, "203.0.113.10")
    respond(monkeypatch, 200, b"x" * 1000)
    assert len(fetch("https://cal.example/x.ics", max_bytes=1000)) == 1000


def test_deadline(monkeypatch):                     # fake clock passes 31 s between chunks → "timeout"
    clock = [1000.0]
    monkeypatch.setattr(net.time, "monotonic", lambda: clock[0])

    class SlowBody(io.BytesIO):
        def read(self, *args):
            clock[0] += 31
            return super().read(*args)

    resolve_to(monkeypatch, "203.0.113.10")
    respond_sequence(monkeypatch, make_response(200, raw=SlowBody(b"x" * 200_000)))
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "timeout"


def test_requests_timeout(monkeypatch):
    resolve_to(monkeypatch, "203.0.113.10")
    respond_raises(monkeypatch, requests.ReadTimeout("read timed out"))
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "timeout"


# ------------------------------------------------------------ errors

def test_http_status_kept(monkeypatch):             # 403 → reason "http", status 403
    resolve_to(monkeypatch, "203.0.113.10")
    respond(monkeypatch, 403, b"Forbidden")
    with pytest.raises(FetchError) as e:
        fetch("https://cal.example/x.ics")
    assert e.value.reason == "http"
    assert e.value.status == 403
    assert str(e.value) == "http 403"


def test_error_text_never_contains_the_link(monkeypatch):
    secret = "tok3nCANARY"
    resolve_to(monkeypatch, "203.0.113.10")
    respond_raises(monkeypatch, requests.ConnectionError(f"Max retries with url: /{secret}/c.ics"))
    with pytest.raises(FetchError) as e:
        fetch(f"https://x.example/{secret}/c.ics")
    assert secret not in str(e.value) and secret not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__     # raised "from None"
    assert e.value.__context__ is None
    assert e.value.reason == "unreachable"


def test_unexpected_errors_become_fetch_errors(monkeypatch):
    secret = "tok3nCANARY"
    def broken_getaddrinfo(*args, **kwargs):
        raise RuntimeError(f"weird failure for {secret}")
    monkeypatch.setattr(net.socket, "getaddrinfo", broken_getaddrinfo)
    with pytest.raises(FetchError) as e:
        fetch(f"https://x.example/{secret}/c.ics")
    assert secret not in str(e.value) and secret not in repr(e.value)
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_dns_failure_is_unreachable(monkeypatch):
    def no_such_host(*args, **kwargs):
        raise socket.gaierror(8, "nodename nor servname provided")
    monkeypatch.setattr(net.socket, "getaddrinfo", no_such_host)
    with pytest.raises(FetchError) as e:
        fetch("https://nowhere.example/x.ics")
    assert e.value.reason == "unreachable"


@pytest.mark.parametrize("url", ["", "ftp://cal.example/x.ics", "file:///etc/passwd",
                                 "https://", "https://[::1/x.ics"])
def test_bad_links(url):
    with pytest.raises(FetchError) as e:
        fetch(url)
    assert e.value.reason == "bad_link"


# ------------------------------------------------------------ local files and webcal

def test_local_file_and_webcal(tmp_path, monkeypatch):
    path = tmp_path / "cal.ics"
    path.write_bytes(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
    assert fetch(str(path)) == b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    with pytest.raises(FetchError) as e:
        fetch(str(path), max_bytes=10)
    assert e.value.reason == "too_large"

    with pytest.raises(FetchError) as e:
        fetch(str(tmp_path / "missing.ics"))
    assert e.value.reason == "unreachable"

    resolve_to(monkeypatch, "203.0.113.10")
    for link in ["webcal://cal.example/x.ics", "WEBCAL://cal.example/x.ics"]:
        calls = respond(monkeypatch, 200, b"BEGIN:VCALENDAR")
        assert fetch(link) == b"BEGIN:VCALENDAR"
        assert calls[0][0] == "https://cal.example/x.ics"


# ------------------------------------------------------------ LAN address

class FakeSocket:
    instances = []

    def __init__(self, own_ip=None, fail=False):
        self.own_ip, self.fail = own_ip, fail
        self.connected_to = None
        self.closed = False
        FakeSocket.instances.append(self)

    def connect(self, address):
        if self.fail:
            raise OSError("Network is unreachable")
        self.connected_to = address

    def getsockname(self):
        return (self.own_ip, 54321)

    def send(self, *args):              # pragma: no cover - must never happen
        raise AssertionError("lan_address must not send packets")

    sendto = send

    def close(self):
        self.closed = True


def fake_socket(monkeypatch, **kwargs):
    FakeSocket.instances = []
    monkeypatch.setattr(net.socket, "socket", lambda *a, **k: FakeSocket(**kwargs))


def host_addresses(monkeypatch, *ips):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (ip, 0)) for ip in ips]
    monkeypatch.setattr(net.socket, "getaddrinfo", fake_getaddrinfo)


def test_lan_address_prefers_private(monkeypatch):
    fake_socket(monkeypatch, own_ip="192.168.1.20")
    host_addresses(monkeypatch, "10.0.0.7")
    assert lan_address() == "192.168.1.20"
    sock, = FakeSocket.instances
    assert sock.connected_to == ("192.0.2.1", 9)
    assert sock.closed


def test_lan_address_falls_back_to_host_addresses(monkeypatch):
    fake_socket(monkeypatch, own_ip="203.0.113.5")          # default route is not private
    host_addresses(monkeypatch, "127.0.1.1", "fe80::1", "203.0.113.5", "172.16.4.2")
    assert lan_address() == "172.16.4.2"
    assert FakeSocket.instances[0].closed


def test_lan_address_none_without_private_address(monkeypatch):
    fake_socket(monkeypatch, fail=True)
    host_addresses(monkeypatch, "127.0.0.1", "::1")
    assert lan_address() is None
    assert FakeSocket.instances[0].closed


def test_lan_address_survives_resolver_errors(monkeypatch):
    fake_socket(monkeypatch, fail=True)
    def no_such_host(*args, **kwargs):
        raise socket.gaierror(8, "nodename nor servname provided")
    monkeypatch.setattr(net.socket, "getaddrinfo", no_such_host)
    assert lan_address() is None
