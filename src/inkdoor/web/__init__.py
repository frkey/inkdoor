"""The admin web app and the public Kindle image route.

Every request goes through one guard (``_guard``), in this order:

1. unknown path (or a known path with the wrong method) -> 404, never a redirect;
2. Host allowlist (DNS rebinding): ``/kindle.png`` gets a 200 error image, anything else a 400;
3. admin disabled -> only ``/kindle.png`` exists;
4. public endpoints (``kindle``, ``login``, ``static``) pass; a POST to them must pass the Origin
   check;
5. a changed password file logs everyone out;
6. a session is required: GET redirects to the login page, anything else gets 401;
7. POST: the Origin check and the session's CSRF token.

Session state lives on the server (``auth.Sessions``); Flask's signed-cookie session is never used
and the app has no secret key.
"""
from __future__ import annotations

import hmac
import io
import math
import os
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urlencode

from flask import Flask, abort, g, redirect, render_template, request, send_from_directory
from markupsafe import Markup, escape
from werkzeug.exceptions import HTTPException

from ..i18n import Translator
from ..render import render_host_rejected
from ..state import IMAGE_NAME, ServerState
from . import auth
from .hosts import host_allowed

SESSION_COOKIE = "inkdoor_session"
LOGIN_COOKIE = "inkdoor_login"
SESSION_LIFETIME = 7 * 86400
PUBLIC_ENDPOINTS = frozenset({"kindle", "login", "static"})
HOST_IMAGE_CACHE = 16
MAX_PASSWORD_LENGTH = 1024
MAX_REQUEST_BYTES = 1024 * 1024

CSP = ("default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
       "form-action 'self'; base-uri 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_HERE, "static")
FONTS_DIR = os.path.join(os.path.dirname(_HERE), "fonts")
# only the bundled font files are served from /static/fonts/, never the rest of the folder
FONT_FILES = frozenset(f for f in os.listdir(FONTS_DIR) if f.endswith(".otf"))
_ERROR_CODES = frozenset({400, 401, 403, 404, 413, 500})


def translator(state: ServerState) -> Translator:
    display = state.cfg.get("display", {}) if isinstance(state.cfg, dict) else {}
    return Translator(state.language or display.get("language"), display.get("clock"))


def _allowed_hosts(state: ServerState) -> list:
    admin = state.cfg.get("admin") if isinstance(state.cfg, dict) else None
    hosts = admin.get("allowed_hosts") if isinstance(admin, dict) else None
    return hosts if isinstance(hosts, list) else []


def add_notice(session: auth.Session, message: str) -> None:
    """Queues a one-shot message shown on the next page this browser loads."""
    session.notices.append(message)


def pop_notices(session: auth.Session | None) -> list[str]:
    messages = []
    if session is not None:
        while session.notices:
            try:
                messages.append(session.notices.pop(0))
            except IndexError:  # another request of the same browser took it
                break
    return messages


def safe_next(value: str | None) -> str:
    """A local path to go to after login; anything that could leave the site becomes "/"."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if "\\" in value or any(ord(c) < 0x21 or ord(c) == 0x7F for c in value):
        return "/"  # browsers drop tabs and newlines and read "\" as "/": "/\t/evil.com"
    return value


def _printable(text: str, limit: int = 60) -> str:
    """A Host header that is safe to put in a log line or on the screen."""
    cleaned = "".join(c if 0x20 < ord(c) < 0x7F else "?" for c in text[:limit])
    return cleaned or "?"


def _origin_matches(origin: str, scheme: str, host: str) -> bool:
    """True when an Origin header names this very scheme, host and port."""
    def normalize(s: str, h: str) -> str:
        s, h = s.lower(), h.lower()
        default = {"http": ":80", "https": ":443"}.get(s)
        if default and h.endswith(default):
            h = h[: -len(default)]
        return f"{s}://{h}"

    other_scheme, sep, other_host = origin.partition("://")
    if not sep or not other_host or "/" in other_host:
        return False
    return normalize(other_scheme, other_host) == normalize(scheme, host)


def _same_token(given, expected: str) -> bool:
    if not isinstance(given, str) or not given:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def create_app(state: ServerState, *, clock=time.time) -> Flask:
    app = Flask(__name__, static_folder=None, template_folder="templates")
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        PROVIDE_AUTOMATIC_OPTIONS=False,  # OPTIONS is not a method we answer
    )
    sessions = auth.Sessions(clock, lifetime=SESSION_LIFETIME)
    limiter = auth.LoginLimiter(clock)
    password_file = auth.password_path(state.config_path)
    watcher = auth.PasswordWatcher(password_file)
    watcher.changed()  # record the file as it is now, so the first change is noticed
    host_images: OrderedDict[tuple[str, str], bytes] = OrderedDict()
    host_lock = threading.Lock()
    app.extensions["inkdoor"] = {"sessions": sessions, "limiter": limiter, "watcher": watcher,
                                 "host_images": host_images}

    def t() -> Translator:
        if "t" not in g:
            g.t = translator(state)
        return g.t

    def page(template: str, status: int = 200, **context):
        return render_template(template, **context), status

    # --- guards -------------------------------------------------------------------------------

    def host_image(raw_host: str) -> bytes:
        shown = _printable(raw_host)
        key = (t().language, shown)
        with host_lock:
            png = host_images.get(key)
            if png is not None:
                host_images.move_to_end(key)
                return png
        app.logger.warning(t()("admin.log_host_rejected", host=shown))
        buffer = io.BytesIO()
        render_host_rejected(state.cfg, shown).save(buffer, format="PNG", optimize=True)
        png = buffer.getvalue()
        with host_lock:
            host_images[key] = png
            while len(host_images) > HOST_IMAGE_CACHE:
                host_images.popitem(last=False)
        return png

    def origin_ok() -> bool:
        origin = request.headers.get("Origin")
        if origin is None:
            return True
        return _origin_matches(origin.strip(), request.scheme, request.headers.get("Host", ""))

    @app.before_request
    def _guard():
        g.session = None
        if request.url_rule is None:
            abort(404)
        raw_host = request.headers.get("Host")  # raw: Werkzeug's request.host is normalized
        if not host_allowed(raw_host, _allowed_hosts(state)):
            if request.endpoint == "kindle":
                return app.response_class(host_image(raw_host or ""), mimetype="image/png",
                                          headers={"Cache-Control": "no-store"})
            return app.response_class(t()("admin.bad_host") + "\n", status=400,
                                      mimetype="text/plain")
        if not state.admin_enabled and request.endpoint != "kindle":
            abort(404)
        if request.endpoint in PUBLIC_ENDPOINTS:
            if request.method == "POST" and not origin_ok():
                abort(403)
            return None
        if watcher.changed():
            sessions.drop_all()
        session = sessions.get(request.cookies.get(SESSION_COOKIE))
        if session is None:
            if request.method in ("GET", "HEAD"):
                return redirect("/login?" + urlencode({"next": request.path}))
            abort(401)
        g.session = session
        if request.method == "POST":
            if not origin_ok() or not _same_token(request.form.get("csrf"), session.csrf):
                abort(403)
        return None

    @app.after_request
    def _headers(response):
        if request.url_rule is not None and request.endpoint == "kindle":
            response.headers["Cache-Control"] = "no-store"
            return response
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.context_processor
    def _template_globals():
        session = g.get("session")

        def csrf_field():
            token = session.csrf if session is not None else ""
            return Markup(f'<input type="hidden" name="csrf" value="{escape(token)}">')

        return {"t": t(), "csrf_field": csrf_field, "logged_in": session is not None,
                "notices": pop_notices(session)}

    # --- errors -------------------------------------------------------------------------------

    def error_page(code: int):
        key = f"admin.error_{code}" if code in _ERROR_CODES else "admin.error_other"
        try:
            return page("error.html", code, code=code, message=t()(key))
        except Exception:  # never let the error page itself fail with details
            return app.response_class(t()(key) + "\n", status=code, mimetype="text/plain")

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        if e.code is None or e.code < 400:
            return e
        return error_page(e.code)

    @app.errorhandler(Exception)
    def _unexpected(e: Exception):
        # only the type: messages and tracebacks can carry calendar links
        app.logger.error(t()("admin.log_error", error=type(e).__name__))
        return error_page(500)

    # --- routes -------------------------------------------------------------------------------

    @app.get("/kindle.png", endpoint="kindle")
    def kindle():
        try:
            with open(os.path.join(state.output_dir, IMAGE_NAME), "rb") as f:
                body = f.read()
        except OSError:
            return app.response_class(t()("admin.not_rendered") + "\n", status=503,
                                      mimetype="text/plain", headers={"Cache-Control": "no-store"})
        return app.response_class(body, mimetype="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/static/<path:filename>", endpoint="static")
    def static(filename: str):
        if filename.startswith("fonts/"):
            name = filename.removeprefix("fonts/")
            if name not in FONT_FILES:
                abort(404)
            return send_from_directory(FONTS_DIR, name)
        return send_from_directory(STATIC_DIR, filename)

    def login_page(status: int = 200, error: str | None = None, next_: str = "/"):
        token = secrets.token_urlsafe(32)
        no_password = auth.read_password_hash(password_file) is None
        body, status = page("login.html", status, token=token, error=error, next=next_,
                            no_password=no_password)
        response = app.make_response((body, status))
        response.set_cookie(LOGIN_COOKIE, token, path="/login", httponly=True, samesite="Strict")
        return response

    def wait_text(seconds: float) -> str:
        if seconds < 60:
            return t()("admin.wait_seconds", n=max(1, math.ceil(seconds)))
        return t().duration(math.ceil(seconds / 60))

    @app.route("/login", methods=["GET", "POST"], endpoint="login")
    def login():
        if watcher.changed():  # e.g. `inkdoor password` just ran: old sessions end here too
            sessions.drop_all()
        current = sessions.get(request.cookies.get(SESSION_COOKIE))
        if request.method != "POST":
            if current is not None:
                return redirect("/")
            return login_page(next_=safe_next(request.args.get("next")))

        next_ = safe_next(request.form.get("next"))
        if not _same_token(request.form.get("csrf"), request.cookies.get(LOGIN_COOKIE) or ""):
            return login_page(400, t()("admin.login_expired"), next_)
        encoded = auth.read_password_hash(password_file)
        if encoded is None:  # fail closed: no file means nobody gets in
            return login_page(503, None, next_)
        ip = request.remote_addr or ""
        wait = limiter.retry_after(ip)  # reserves this attempt; checked before scrypt
        if wait > 0:
            return login_page(429, t()("admin.try_again", wait=wait_text(wait)), next_)
        ok = False
        try:
            password = request.form.get("password", "")
            ok = len(password) <= MAX_PASSWORD_LENGTH and auth.verify_password(password, encoded)
        finally:
            (limiter.succeeded if ok else limiter.failed)(ip)
        if not ok:
            return login_page(401, t()("admin.wrong_password"), next_)

        if current is not None:
            sessions.drop(current.sid)  # this browser gets a fresh id
        session = sessions.create()
        response = redirect(next_)
        response.set_cookie(SESSION_COOKIE, session.sid, max_age=SESSION_LIFETIME, path="/",
                            httponly=True, samesite="Strict")
        response.delete_cookie(LOGIN_COOKIE, path="/login", httponly=True, samesite="Strict")
        return response

    @app.post("/logout", endpoint="logout")
    def logout():
        sessions.drop(g.session.sid)
        response = redirect("/login")
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="Strict")
        return response

    @app.get("/", endpoint="home")
    def home():
        image = os.path.join(state.output_dir, IMAGE_NAME)
        try:
            preview = os.stat(image).st_mtime_ns // 1_000_000
        except OSError:
            preview = None
        last = state.last_render
        updated = None
        if last is not None:
            updated = t()("admin.last_update", date=t().date_short(last.at), time=t().time(last.at))
        return page("home.html", last=last, updated=updated, preview=preview)

    return app
