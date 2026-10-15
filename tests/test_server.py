import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from inkdoor.server import make_handler


@pytest.fixture
def server(tmp_path):
    image = tmp_path / "kindle.png"
    image.write_bytes(b"\x89PNG fake")
    (tmp_path / "config.toml").write_text("secret")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(str(image)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_serves_only_the_image(server, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    assert get(server + "/kindle.png") == (200, b"\x89PNG fake")
    assert get(server + "/kindle.png?t=1")[0] == 200
    for path in ("/", "/config.toml", "/../config.toml", "/kindle.png/"):
        assert get(server + path)[0] == 404


def test_cycle_keeps_last_valid_config_and_never_leaves_a_stale_screen(tmp_path, monkeypatch, cfg):
    from inkdoor import server

    path = tmp_path / "config.toml"
    path.write_text("[server]\nrefresh_minutes = 0\n")       # broken on purpose
    out = tmp_path / "out"
    kept = server.run_cycle(str(path), str(out), None, cfg, server.SourceCache())
    assert kept is cfg and (out / "kindle.png").exists()

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(server, "render", boom)
    before = (out / "kindle.png").read_bytes()
    server.run_cycle(str(path), str(out), None, cfg, server.SourceCache())
    assert (out / "kindle.png").read_bytes() != before   # replaced by the error screen
