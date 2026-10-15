"""Renders the screen periodically and serves it over HTTP for the Kindle to download."""
from __future__ import annotations

import os
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .render import render, translator_for
from .sources import collect

IMAGE_NAME = "kindle.png"


def save(img, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp.png"
    img.save(tmp, optimize=True)
    os.replace(tmp, path)  # atomic swap: the Kindle never downloads half an image


def render_once(cfg: dict, output_dir: str) -> str:
    t = translator_for(cfg)
    snap = collect(cfg)
    path = os.path.join(output_dir, IMAGE_NAME)
    save(render(snap, cfg), path)
    line = t("cli.rendered", time=t.time(snap.now), events=len(snap.today), tasks=len(snap.tasks))
    if snap.errors:
        line += t("cli.rendered_errors", sources="; ".join(snap.errors))
    print(line)
    return path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(config_path: str | None, output_dir: str) -> None:
    cfg = config.load(config_path)
    t = translator_for(cfg)
    port = cfg["server"]["port"]
    os.makedirs(output_dir, exist_ok=True)
    handler = partial(_QuietHandler, directory=os.path.abspath(output_dir))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(t("cli.serving", port=port))
    while True:
        try:
            cfg = config.load(config_path)  # reloaded every cycle: edit without restarting
            render_once(cfg, output_dir)
        except Exception as ex:  # never let one bad calendar stop the server
            print(translator_for(cfg)("cli.error", error=ex))
        time.sleep(cfg["server"]["refresh_minutes"] * 60)
