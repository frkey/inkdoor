"""Renders the screen periodically and serves it over HTTP for the Kindle to download."""
from __future__ import annotations

import errno
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .i18n import Translator
from .render import render, render_error, translator_for
from .sources import SourceCache, collect
from .state import IMAGE_NAME


def save(img, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp.png"
    img.save(tmp, optimize=True)
    os.replace(tmp, path)  # atomic swap: the Kindle never downloads half an image


def render_once(cfg: dict, output_dir: str, cache: SourceCache | None = None) -> str:
    t = translator_for(cfg)
    snap = collect(cfg, cache=cache)
    path = os.path.join(output_dir, IMAGE_NAME)
    save(render(snap, cfg), path)
    line = t("cli.rendered", time=t.time(snap.now), events=len(snap.today), tasks=len(snap.tasks))
    if snap.errors:
        line += t("cli.rendered_errors", sources="; ".join(snap.errors))
    print(line)
    return path


def make_handler(image_path: str):
    """A handler that serves the screen image and nothing else (no directory listing)."""

    class ImageOnly(BaseHTTPRequestHandler):
        def do_GET(self, head_only=False):
            if self.path.split("?")[0] != "/" + IMAGE_NAME:
                self.send_error(404)
                return
            try:
                with open(image_path, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET(head_only=True)

        def log_message(self, *args):
            pass

    return ImageOnly


def serve(config_path: str | None, output_dir: str, language: str | None = None) -> None:
    cfg = config.load(config_path, language)
    t = translator_for(cfg)
    port = cfg["server"]["port"]
    image_path = os.path.join(output_dir, IMAGE_NAME)
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(os.path.abspath(image_path)))
    except OSError as ex:
        if ex.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)):
            raise PortInUse(port) from None
        raise
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(t("cli.serving", port=port))

    cache = SourceCache()
    while True:
        cfg = run_cycle(config_path, output_dir, language, cfg, cache)
        time.sleep(cfg["server"]["refresh_minutes"] * 60)


def run_cycle(config_path, output_dir, language, last_cfg: dict, cache: SourceCache) -> dict:
    """One refresh. Returns the config to keep using (the last valid one if the file broke)."""
    cfg = last_cfg
    try:  # reloaded every cycle so the config can be edited without restarting
        cfg = config.load(config_path, language)
    except Exception as ex:  # any problem with the file: keep running on the last valid config
        t = translator_for(last_cfg)
        print(t("cli.kept_last_config", message=describe(ex, t)))
    try:
        render_once(cfg, output_dir, cache)
    except Exception as ex:
        # never leave an old status on the door: show an error screen instead
        print(translator_for(cfg)("cli.error", error=ex))
        # only the error type goes on the door: messages can contain local paths
        save(render_error(cfg, ex.__class__.__name__), os.path.join(output_dir, IMAGE_NAME))
    return cfg


class PortInUse(Exception):
    def __init__(self, port: int):
        super().__init__(port)
        self.port = port


def describe(ex: Exception, t: Translator) -> str:
    """Human-readable, translated explanation of a config problem."""
    if isinstance(ex, config.ConfigInvalid):
        return t(f"config_error.{ex.key}", **ex.details)
    if isinstance(ex, config.ConfigMissing):
        return t("cli.config_missing", path=ex.path)
    return str(ex)
