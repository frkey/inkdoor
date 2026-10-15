"""Renders the screen in a background loop and serves it, with the admin, through Waitress.

Only the render loop renders. The admin asks for a new render by setting
``ServerState.render_event``; the loop clears the event before each cycle and then waits on it
with the refresh interval as timeout, so a request that arrives during a render is not lost.
"""
from __future__ import annotations

import datetime as dt
import errno
import os
import threading
from zoneinfo import ZoneInfo

from . import config, net
from .render import compute_status, render, render_error, render_setup, translator_for
from .sources import SourceCache, Snapshot, collect
from .state import IMAGE_NAME, RenderInfo, ServerState

THREADS = 8


class PortInUse(Exception):
    def __init__(self, port: int):
        super().__init__(port)
        self.port = port


def save(img, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp.png"
    img.save(tmp, optimize=True)
    os.replace(tmp, path)  # atomic swap: the Kindle never downloads half an image


def compose(snap: Snapshot, cfg: dict, admin_url: str | None):
    """The door image for a snapshot, with its status word and headline.

    With no calendar and no tasks configured the door shows the setup screen, never "Free".
    """
    t = translator_for(cfg)
    if snap.configured == "nothing":
        return render_setup(cfg, admin_url), t("status.setup"), t("status.setup_headline")
    status = compute_status(snap, cfg, t)
    return render(snap, cfg), status.word, status.headline


def _render_snapshot(cfg: dict, path: str, cache: SourceCache | None,
                     admin_url: str | None) -> RenderInfo:
    t = translator_for(cfg)
    snap = collect(cfg, cache=cache)
    img, word, headline = compose(snap, cfg, admin_url)
    save(img, path)
    line = t("cli.rendered", time=t.time(snap.now), events=len(snap.today), tasks=len(snap.tasks))
    if snap.errors:  # "Name: ErrorType" only, never a link
        line += t("cli.rendered_errors", sources="; ".join(snap.errors))
    print(line)
    return RenderInfo(snap.now, word, headline, list(snap.errors))


def render_once(cfg: dict, output_dir: str, cache: SourceCache | None = None) -> str:
    path = os.path.join(output_dir, IMAGE_NAME)
    admin_url = net.admin_url(cfg) if cfg["admin"]["enabled"] else None
    _render_snapshot(cfg, path, cache, admin_url)
    return path


# ---------------------------------------------------------------- startup

def _startup_config(path: str, language: str | None) -> tuple[dict, str | None, bool]:
    """(cfg, problem, using_defaults): the file, else its .bak, else the defaults."""
    try:
        return config.load(path, language), None, False
    except Exception:  # any problem with the file: serve must still come up
        pass
    try:
        return config.load(path + ".bak", language), "broken", False
    except Exception:
        pass
    cfg = config.with_defaults({})
    language = language or os.environ.get("INKDOOR_LANG")
    if language:
        cfg["display"]["language"] = language
    return cfg, ("broken" if os.path.lexists(path) else "missing"), True


def load_for_serve(config_path: str | None, language: str | None) -> tuple[dict, str | None]:
    """The config ``serve`` starts with, and what is wrong with the file.

    Returns ``(cfg, None)`` when the file loads, ``(cfg, "broken")`` when only
    ``config.toml.bak`` loads, and the defaults with ``"missing"`` or ``"broken"`` otherwise.
    """
    cfg, problem, _ = _startup_config(config.resolve_path(config_path), language)
    return cfg, problem


# ---------------------------------------------------------------- render loop

def _now(cfg: dict) -> dt.datetime:
    try:
        return dt.datetime.now(ZoneInfo(cfg["display"]["timezone"]))
    except Exception:
        return dt.datetime.now().astimezone()


def _reason(ex: Exception) -> str:
    """What went wrong with the config, without any of its content."""
    return ex.key if isinstance(ex, config.ConfigInvalid) else type(ex).__name__


def _reload(state: ServerState) -> None:
    """Reloads the config every cycle, so it can be edited without restarting."""
    try:
        cfg = config.load(state.config_path, state.language)
    except Exception as ex:  # keep running on the last valid config (or the defaults)
        missing = isinstance(ex, config.ConfigMissing)
        state.config_problem = "missing" if missing and state.using_defaults else "broken"
        t = translator_for(state.cfg)
        key = "cli.config_defaults" if state.using_defaults else "cli.kept_last_config"
        print(t(key, message=_reason(ex)))
        return
    state.cfg = cfg
    state.config_problem = None
    state.using_defaults = False


def run_cycle(state: ServerState, cache: SourceCache) -> None:
    """One refresh: reload the config, render the door and record what it shows."""
    _reload(state)
    cfg = state.cfg
    t = translator_for(cfg)
    path = os.path.join(state.output_dir, IMAGE_NAME)
    try:
        admin_url = net.admin_url(cfg) if state.admin_enabled else None
        if state.using_defaults and state.config_problem == "missing":
            save(render_setup(cfg, admin_url), path)
            info = RenderInfo(_now(cfg), t("status.setup"), t("status.setup_headline"), [])
        elif state.using_defaults:  # a broken file and nothing valid to fall back on
            save(render_error(cfg, config.ConfigInvalid.__name__), path)
            info = RenderInfo(_now(cfg), t("status.unknown"), t("status.error_headline"), [])
        else:
            info = _render_snapshot(cfg, path, cache, admin_url)
    except Exception as ex:
        # never leave an old status on the door: show an error screen instead. Only the error
        # type is printed or drawn: messages can carry local paths or links
        name = ex.__class__.__name__
        print(t("cli.error", error=name))
        save(render_error(cfg, name), path)
        info = RenderInfo(_now(cfg), t("status.unknown"), t("status.error_headline"), [])
    state.last_render = info


def render_loop(state: ServerState, cache: SourceCache, stop: threading.Event) -> None:
    """Renders every ``refresh_minutes`` and whenever ``state.render_event`` is set.

    To end it, set ``stop`` and then ``render_event`` (which wakes the wait).
    """
    while not stop.is_set():
        state.render_event.clear()
        try:
            run_cycle(state, cache)
        except Exception as ex:  # e.g. the output folder is not writable: try again later
            print(translator_for(state.cfg)("cli.error", error=ex.__class__.__name__))
        state.render_event.wait(state.cfg["server"]["refresh_minutes"] * 60)


# ---------------------------------------------------------------- serve

def _run(httpd) -> None:
    httpd.run()  # returns after Ctrl+C


def serve(config_path: str | None, output_dir: str, language: str | None = None) -> None:
    import waitress

    from .web import auth, create_app  # only serve needs the web stack, not render or demo

    path = config.resolve_path(config_path)
    cfg, problem, using_defaults = _startup_config(path, language)
    t = translator_for(cfg)
    port = cfg["server"]["port"]
    state = ServerState(path, output_dir, language, cfg, problem, cfg["admin"]["enabled"],
                        using_defaults=using_defaults)
    app = create_app(state)
    try:
        # trusted_proxy stays unset: X-Forwarded-* headers are never trusted
        httpd = waitress.create_server(app, host="0.0.0.0", port=port, threads=THREADS)
    except OSError as ex:
        if ex.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)):
            raise PortInUse(port) from None
        raise

    stop = threading.Event()
    try:
        print(t("cli.serving", port=port))
        if state.admin_enabled and auth.read_password_hash(auth.password_path(path)) is None:
            print(t("cli.no_password"))
        threading.Thread(target=render_loop, args=(state, SourceCache(), stop),
                         name="inkdoor-render", daemon=True).start()
        _run(httpd)
    finally:
        stop.set()
        state.render_event.set()
        httpd.close()
