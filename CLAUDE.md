# CLAUDE.md

Guidance for Claude (and other contributors) working on this repository.

## Language policy

- **Everything in the repository is written in English**: code, identifiers, comments,
  docstrings, commit messages, pull requests, issues, tests, CI, and technical docs.
  This applies even when the conversation with the maintainer happens in Portuguese.
- **User-facing text is internationalized.** Never hard-code a string that a user can see
  (on the Kindle screen, in CLI output, or in Kindle script messages). Instead:
  - Python: add a key to `src/inkdoor/locales/en-US.json` and use the `Translator`
    (`t("section.key", name=value)`). Plurals use `{"one": ..., "other": ...}` and `n=`.
  - Kindle shell scripts: add a `MSG_*` variable to both branches of the `case "$LANGUAGE"`
    block in `kindle/inkdoor/common.sh`. Keep those strings ASCII; the Kindle's built-in
    screen font has no accents.
  - Deploy scripts (`deploy/`): add a `MSG_*` variable to both branches of the script's
    `case "$LANGUAGE"` block. These run in a terminal, so pt-BR strings use accents.
- **en-US is the default and the reference locale.** Every key must exist in `en-US.json`.
- **pt-BR is a first-class option and must stay in sync.** Whenever you add or change a key in
  `en-US.json`, update `pt-BR.json` in the same change. `tests/test_i18n.py` fails if the
  catalogs have different keys.
- Write en-US text in US English: "canceled", "color", 12-hour clock with AM/PM, "Oct 14".
  Write pt-BR text in natural Brazilian Portuguese with the 24-hour clock ("14:30").
- Format times, dates and durations through `Translator.time()`, `.date_short()`,
  `.date_header()` and `.duration()`, never with ad-hoc f-strings.
- **User docs exist in both languages.** `README.md` (English) is mirrored by
  `README.pt-BR.md`, and each file in `docs/` has a translation in `docs/pt-BR/`. Update both
  in the same change. Developer-only docs (this file, code comments) are English only.
- Demo content in `src/inkdoor/demo.py` exists per language; add an entry for any new locale.

## Project overview

inkdoor turns a jailbroken Kindle into a door sign that shows whether you are in a meeting.

- `src/inkdoor/`: Python package that runs on a computer. It reads ICS calendars and a
  TickTick subscription (`sources.py`), draws a 1072×1448 grayscale PNG (`render.py`) and
  serves it over HTTP with Waitress (`server.py`, render loop plus `serve()`). `net.py` fetches
  links and finds the LAN address; `state.py` holds what the render loop and the admin share;
  `files.py` writes private (mode 600) files atomically; `config_edit.py` edits `config.toml`
  as it is on disk for the admin.
- `src/inkdoor/web/`: the web admin (Flask, served on the same port as the image): routes and
  guards (`__init__.py`), password and sessions (`auth.py`), Host allowlist (`hosts.py`), pages
  and forms, Jinja templates and first-party static files.
- `kindle/`: POSIX shell scripts that run on the Kindle and display the PNG.
- `deploy/`: runs `inkdoor serve` as a systemd service. `install.sh` installs or updates it on
  Debian/Ubuntu; `proxmox/create-lxc.sh` runs on a Proxmox VE host, creates an LXC container and
  runs `install.sh` in it.

## Commands

```sh
pip install -e ".[dev]"
pytest                                   # all tests
inkdoor -o output demo 10:20 16:50       # render previews with fictional data
inkdoor -o output --lang pt-BR demo 10:20
cd kindle && shellcheck inkdoor/*.sh documents/*.sh
shellcheck deploy/*.sh deploy/proxmox/*.sh
```

After changing anything visual, render the demo in **both** languages at a few times
(e.g. 7:30, 10:20, 15:20, 16:50, 21:10) and look at the images: Portuguese strings are often
longer and are the usual cause of overflow.

## Conventions

- Default branch: `master`.
- Supported Python: 3.10+ (`tomli` is used as a fallback for `tomllib` on 3.10).
- Screen constraints: 1072×1448 px, 16 gray levels (multiples of 17). `render()` snaps every
  pixel to those levels; keep strokes at least 3 px wide so they survive e-ink.
- Calendars are never merged with each other; only repeats inside one calendar are
  de-duplicated.
- The door must never say "Free" without knowing. If a busy calendar cannot be read, the
  server reuses that calendar's last good data for the day (`SourceCache`), and with no data
  at all the status becomes "Knock first". If rendering fails, an error screen replaces the
  old image.
- `/kindle.png` is public (so are the login page and the admin's bundled static files); every
  other route requires the admin login, and unknown paths are 404. Never serve the output folder
  or config files.
- Fetch calendar and task links only through `inkdoor.net.fetch` (size cap, deadline, redirect
  limit, no loopback or link-local). Links are secrets: never put them in a response, a log line
  or an exception message.
- Kindle scripts must be POSIX `sh` (BusyBox), use LF line endings (`.gitattributes` enforces
  it), and pass ShellCheck with `kindle/.shellcheckrc`.
- Deploy scripts are bash (Debian/Ubuntu and Proxmox hosts), must be idempotent (running
  `install.sh` again is how users update) and must never overwrite `/etc/inkdoor/config.toml`
  or `admin-password` (the one change allowed is adding `[admin] enabled = true` once).
  `/etc/inkdoor` is `inkdoor:inkdoor` 700 and every file in it 600; the admin writes there.
  Keep `inkdoor.service` sandboxed; if you add an option, check it still starts in an
  unprivileged LXC container with nesting.
- Fonts in `src/inkdoor/fonts/` are a Latin subset of Inter (SIL OFL 1.1). If you need a glyph
  outside that subset, re-subset from the upstream font and keep `OFL.txt`.

## Privacy

This is a public repository.

- Never commit `config.toml` (or its `.bak`/`.tmp` copies) or `admin-password`; they hold
  secret calendar links and the admin password hash and are git-ignored.
- Never put real calendar URLs, names, email addresses or meeting titles in code, tests, docs or
  screenshots. Use the fictional data in `demo.py` and `tests/fixtures/`.
