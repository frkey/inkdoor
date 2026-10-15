"""`inkdoor serve` against a real Waitress socket: Host parsing and the startup path."""
import http.client
import io
import os
import socket
import threading
import time

import pytest
from PIL import Image

from inkdoor import server
from inkdoor.i18n import Translator

EN = Translator("en-US")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"server did not start on port {port}")


def request(port: int, path: str, host: str) -> tuple[int, dict, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def raw_request(port: int, path: str, version: str = "HTTP/1.1") -> tuple[int, bytes]:
    """A request without any Host header (http.client always adds one)."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(f"GET {path} {version}\r\nConnection: close\r\n\r\n".encode("ascii"))
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body


@pytest.fixture(scope="module")
def running(tmp_path_factory):
    folder = tmp_path_factory.mktemp("serve")
    port = free_port()
    config_path = folder / "config.toml"
    config_path.write_text(f'[display]\nlanguage = "en-US"\n\n[server]\nport = {port}\n\n'
                           "[admin]\nenabled = true\n")
    out = folder / "out"
    old = os.environ.pop("INKDOOR_LANG", None)
    thread = threading.Thread(target=server.serve, args=(str(config_path), str(out), None),
                              daemon=True)
    thread.start()
    wait_for_port(port)
    deadline = time.monotonic() + 10
    while request(port, "/kindle.png", f"127.0.0.1:{port}")[0] != 200:   # first render
        assert time.monotonic() < deadline, "no image rendered"
        time.sleep(0.05)
    yield port, out
    if old is not None:
        os.environ["INKDOOR_LANG"] = old


def is_png(body: bytes) -> bool:
    return Image.open(io.BytesIO(body)).format == "PNG"


@pytest.mark.parametrize("host", ["[::1]:{port}", "inkdoor.lan.", "[fe80::1]", "localhost:{port}"])
def test_allowed_hosts(running, host):
    port, out = running
    host = host.format(port=port)
    status, headers, body = request(port, "/kindle.png", host)
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert body == (out / "kindle.png").read_bytes()
    status, headers, _ = request(port, "/", host)
    assert status == 302 and headers["Location"].endswith("/login?next=%2F")


@pytest.mark.parametrize("host", ["evil.com", "evil.com.", "inkdoor.lan.evil.com", "[fe80::1%25en0]"])
def test_rejected_hosts(running, host):
    port, out = running
    status, headers, body = request(port, "/", host)
    assert status == 400 and headers["Content-Type"].startswith("text/plain")
    assert body.decode("utf-8").strip() == EN("admin.bad_host")
    status, headers, body = request(port, "/kindle.png", host)
    assert status == 200 and headers["Content-Type"] == "image/png" and is_png(body)
    assert body != (out / "kindle.png").read_bytes()               # the error image, not the door


@pytest.mark.parametrize("version", ["HTTP/1.0", "HTTP/1.1"])
def test_missing_host(running, version):
    port, out = running
    status, body = raw_request(port, "/", version)
    assert status == 400
    status, body = raw_request(port, "/kindle.png", version)
    assert status == 200 and is_png(body) and body != (out / "kindle.png").read_bytes()


def test_unknown_paths_are_404(running):
    port, _ = running
    for path in ("/config.toml", "/out/kindle.png", "/kindle.png/", "/../config.toml"):
        assert request(port, path, f"127.0.0.1:{port}")[0] == 404


def test_port_in_use(tmp_path, monkeypatch):
    monkeypatch.delenv("INKDOOR_LANG", raising=False)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("0.0.0.0", 0))
        busy.listen()
        port = busy.getsockname()[1]
        (tmp_path / "config.toml").write_text(f"[server]\nport = {port}\n")
        with pytest.raises(server.PortInUse) as info:
            server.serve(str(tmp_path / "config.toml"), str(tmp_path / "out"), None)
    assert info.value.port == port
    assert not (tmp_path / "out" / "kindle.png").exists()   # nothing rendered for a dead server


def test_serve_warns_when_the_admin_has_no_password(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("INKDOOR_LANG", raising=False)
    port = free_port()
    (tmp_path / "config.toml").write_text(f"[server]\nport = {port}\n\n[admin]\nenabled = true\n")
    monkeypatch.setattr(server, "_run", lambda httpd: None)        # do not block in the test
    monkeypatch.setattr(server, "render_loop", lambda *args: None)
    server.serve(str(tmp_path / "config.toml"), str(tmp_path / "out"), None)
    out = capsys.readouterr().out
    assert EN("cli.no_password") in out
    assert EN("cli.serving", port=port) in out


def test_serve_does_not_warn_with_a_password_or_without_the_admin(tmp_path, monkeypatch, capsys):
    from inkdoor.web import auth
    monkeypatch.delenv("INKDOOR_LANG", raising=False)
    monkeypatch.setattr(server, "_run", lambda httpd: None)
    monkeypatch.setattr(server, "render_loop", lambda *args: None)
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[server]\nport = {free_port()}\n")               # admin disabled
    server.serve(str(config_path), str(tmp_path / "out"), None)
    assert EN("cli.no_password") not in capsys.readouterr().out

    config_path.write_text(f"[server]\nport = {free_port()}\n\n[admin]\nenabled = true\n")
    auth.set_password(auth.password_path(str(config_path)), "test-pass-not-real-1")
    server.serve(str(config_path), str(tmp_path / "out"), None)
    out = capsys.readouterr().out
    assert EN("cli.no_password") not in out and "test-pass-not-real-1" not in out
