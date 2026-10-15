# Web admin: design

Status: approved in conversation on 2026-10-15, pending written-spec review.

## Goal

Configure inkdoor from a browser instead of editing `config.toml` and copying it into a server or
container. After installing (for example with `deploy/proxmox/create-lxc.sh`), a user opens
`http://<server-ip>:8000`, logs in with a generated password, pastes calendar links, tests them
and sees the door screen update, without touching a terminal again.

Users: the maintainer first, but the repository is public, so it must be safe and clear for
anyone who installs it on a home network.

## Decisions already made

| Topic | Decision |
|---|---|
| Scope | The whole config: calendars, tasks, display settings, plus a live preview of the screen. Not logs, updates or restarts. |
| Transport | Plain HTTP on the LAN. No TLS. |
| Port | The same port as the Kindle image (`[server] port`, default 8000). |
| First password | Random, generated at install time and printed by the installer (or by `inkdoor serve` on first run). |
| Stack | Flask + Jinja templates + Waitress, server-rendered pages, small first-party JS for progressive enhancement. |

### Accepted risk

Without TLS, anyone who can observe LAN traffic (someone on the Wi-Fi who knows its password, a
compromised device) can read the admin password when it is typed at login and a calendar link at
the moment it is pasted. Browsers expose `crypto.subtle` only in secure contexts, so client-side
hashing is not an option. Mitigations below keep everything else from leaking. Anyone who gets in
can read calendars and change the door; they cannot run code on the server.

## Architecture

One process, one port. `inkdoor serve`:

1. Loads the config, creates the Flask app and serves it with Waitress on `0.0.0.0:<port>`
   (bind errors map to the existing `PortInUse` message).
2. Runs the render loop in a background thread, as today. The loop waits on a
   `threading.Event` with the refresh interval as timeout, so the admin can request an
   immediate re-render after a save or from the "Update now" button.

Routes:

| Route | Access | Purpose |
|---|---|---|
| `GET/HEAD /kindle.png` | public | Unchanged contract: exact path (query string allowed), `image/png`, `Cache-Control: no-store`, 503 when not rendered yet, 404 for `/kindle.png/` and anything else unknown. |
| `GET/POST /login` | public | Password form. |
| `GET /static/<file>` | public | CSS, JS, Inter font. Only files shipped in the package. |
| everything else | session | Admin pages and actions. Unauthenticated GET redirects to `/login`; other methods get 401. |

With `[admin] enabled = false`, only `/kindle.png` is routed (today's behavior).

Code layout:

```
src/inkdoor/
  server.py            render loop + serve(): builds the app, runs Waitress
  web/
    __init__.py        create_app(state): routes, before_request guards, headers
    auth.py            password hashing, password file, sessions, login rate limit
    hosts.py           Host header allowlist
    config_edit.py     read/modify/validate/write config.toml (atomic, .bak, concurrency token)
    templates/         Jinja templates (autoescape on)
    static/            admin.css, admin.js
  check.py             structured results shared by `inkdoor check` and the admin "Test" button
```

Shared state between the render loop and the app (`ServerState`): config path, output dir, the
last `Snapshot` summary (time, status text, per-source errors), the render `Event`, and a lock
around config writes.

## Configuration storage

`config.toml` stays the single source of truth; hand-editing keeps working.

- **Reading**: every admin page reads the file fresh through `config.load()`.
- **Writing**: the admin builds the full dict, runs `with_defaults` + `validate`, serializes with
  `tomli-w`, writes `config.toml.tmp`, `fsync`, copies the current file to `config.toml.bak`, then
  `os.replace`. File mode 600. Comments from the example are lost on the first admin save; keys
  the admin does not manage are preserved.
- **Concurrent edits**: each form carries the SHA-256 of the file as it was read. On save, if the
  file changed meanwhile (a hand edit or another tab), the save is refused with a "changed
  elsewhere, reload" message.
- **Broken file on disk** (hand edit with a syntax error): pages show the translated config error
  and disable the forms; if `config.toml.bak` loads, offer "Restore previous version".
- **New section** `[admin]`: `enabled` (default `true`), `allowed_hosts` (default `[]`).
- **Server install**: `/etc/inkdoor` becomes `inkdoor:inkdoor 700`, `config.toml` 600, and the
  unit gets `ReadWritePaths=/etc/inkdoor`. The rest of the sandbox is unchanged.

## Password and sessions

- **Password file**: `admin-password` in the same directory as `config.toml`, mode 600, one line:
  `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>` (`hashlib.scrypt`, n=2^14, r=8, p=1, 16-byte salt).
  Compared with `hmac.compare_digest`. Added to `.gitignore`.
- **Generated password**: 16 characters from an alphabet without look-alikes
  (`23456789abcdefghjkmnpqrstuvwxyz`), shown in groups of four (`k7mq-x3vt-9hwp-r2nd`), about 78
  bits. Dashes are ignored when checking.
- **Who generates it**: `inkdoor password` (new CLI command) writes a new hash and prints the
  password once. `install.sh` calls it when the file does not exist and prints the result with the
  admin URL. `inkdoor serve` does the same on startup when the file is missing (the Mac case).
- **Changing it**: the Account page requires the current password; the new one must have at least
  12 characters, or the user picks "generate".
- **Sessions**: 32 random bytes (`secrets.token_urlsafe`), kept in memory in the server, cookie
  `inkdoor_session` with `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Secure` (HTTP). Lifetime 7
  days. A restart logs everyone out. Any change to the password file (detected by its hash on each
  request) drops all sessions, so `inkdoor password` from a shell logs out the browser.
- **Rate limit**: per client IP, after 5 failed logins each further attempt must wait
  1, 2, 4 … 60 minutes; plus a global cap of 30 failures per hour. Counters live in memory.

## Request guards (every request)

1. **Host allowlist** (DNS rebinding): accept IP literals, `localhost`, single-label names, names
   ending in `.local`, `.lan`, `.home.arpa`, `.internal`, and `[admin] allowed_hosts`. Otherwise
   400. Applies to `/kindle.png` too.
2. **CSRF**: every POST carries a per-session token in a hidden field; also, when `Origin` is
   present it must match the request's scheme, host and port.
3. **Headers** on admin responses: `Content-Security-Policy: default-src 'self'; img-src 'self'
   data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'`,
   `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.

## Secret links

- Never sent back to the browser. Shown masked: host plus the last four characters,
  `outlook.office365.com/…a3f9`.
- Edit forms leave the link field empty; empty means "keep the current link".
- Never logged, never part of test messages or error pages.
- The admin accepts only `http://`, `https://` and `webcal://` links. Local file paths stay
  possible by hand-editing the file, so the admin cannot be used to probe the server's files.

## Pages

All pages: shared menu, mobile friendly, light/dark from the OS, bundled Inter font, no external
resources. Text comes from `locales/*.json` under `admin.*`, in the configured screen language.
Pages work without JavaScript; `admin.js` only enhances (test a link without reloading, copy the
Kindle URL).

1. **Login**: password field.
2. **Home**: preview of the current screen (authenticated route serving the same PNG), door status,
   last update time, failing sources, "Update now", the Kindle URL with a copy button, and a
   banner while no busy calendar has a link.
3. **Calendars**: one card per calendar (name, marker style with a drawn sample, busy toggle,
   status label, masked link); test, edit, remove, move up/down; add calendar. "Test" shows the
   result inline: reachable or not, events in the next 14 days, the next three, and the existing
   warnings (busy-only titles, likely wrong time zone).
4. **Tasks**: TickTick link (masked), name, `overdue_days`, test.
5. **Screen**: language, time zone (searchable list from `zoneinfo.available_timezones()`), clock
   (12h/24h/automatic), workday start/end, workdays, `min_gap_minutes`, `refresh_minutes`. The port
   is shown read-only with a note that changing it means editing the file and restarting.
6. **Account**: change password, log out.

On save: field errors next to the field (reusing `config_error.*` messages); on success the screen
is re-rendered and the preview refreshes.

`check.py` is refactored to return structured results (per source: ok/warn/fail messages, event
count, next events). `inkdoor check` prints them exactly as today; the admin renders them.

## Setup screen instead of "Free"

Today, calendars without a link are skipped silently, so a fresh config makes the door say
FREE. New rule: the door may only say Free when at least one busy calendar has a link. Otherwise
it shows a setup screen: "Set up inkdoor at http://<ip>:<port>". The IP is the address of the
default-route interface (UDP-socket trick, no packet sent), falling back to the hostname.

## Install and deploy changes

- `install.sh`: no longer waits for a link before starting the service (the setup screen covers
  it). Fresh install: generate the password, start the service, print admin URL and password.
  Update: keep the password, remind that `inkdoor password` makes a new one. Migrate old installs:
  chown `/etc/inkdoor` to `inkdoor`, generate a password if missing.
- `inkdoor.service`: `ReadWritePaths=/etc/inkdoor`.
- `create-lxc.sh`: `--config` stays optional; the docs make "create, open the admin, paste links"
  the main path.
- `pyproject.toml`: add `flask`, `waitress`, `tomli-w`.
- `CLAUDE.md`: server rule becomes "`/kindle.png` is public; everything else requires the admin
  login; never serve the output folder or config files".
- Docs (en-US and pt-BR): `docs/server.md`, `README.md` and translations present the admin as the
  main way to configure; hand-editing stays documented.

## Testing

Automated (pytest, Flask test client):

- Route inventory: walk `app.url_map`; every rule except `/kindle.png`, `/login` and `/static`
  must reject anonymous requests. A new unprotected route fails the test.
- `/kindle.png` keeps today's contract (port the existing server tests).
- Host allowlist accepts and rejects the expected names.
- Login success/failure, backoff timing (clock injected), global cap, session expiry, logout,
  password change and password-file change drop sessions.
- CSRF: POST without token, with a wrong token and with a foreign `Origin` are rejected.
- Secrets: after saving calendars and tasks, no admin response contains any full link.
- File paths and other schemes are rejected as links.
- Config writes: atomic replace, `.bak` created, mode 600, round-trip keeps values and unknown
  keys, concurrent-change refusal, restore from `.bak`.
- Setup screen: no busy calendar with a link renders the setup status, never Free.
- `inkdoor check` output unchanged after the refactor.
- `tests/test_i18n.py` already enforces matching `admin.*` keys in both catalogs.

Manual: fresh install in a Debian 12 machine; in the in-app browser, log in, paste a public test
calendar, test it, see the preview update; render the setup screen in both languages.

## Out of scope

HTTPS, multiple users or roles, logs/updates/restarts from the admin, changing the port from the
admin, OAuth logins to Google or Microsoft, admin screenshots in the docs.
