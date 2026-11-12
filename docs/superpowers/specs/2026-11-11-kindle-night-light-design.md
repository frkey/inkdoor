# Kindle night light: design

Status: approved in conversation on 2026-11-11. Pending written-spec review.

## Goal

A Kindle left on all night as a door sign lights up the room. The e-ink panel emits no light (the
image stays visible without power); the light comes from the Kindle's **frontlight**, which the
inkdoor scripts never touch today: it stays at whatever level it had when the display started.

Add an optional schedule that turns the frontlight off during a period of the day (for example
22:00 to 07:00) and brings it back to its previous level when the period ends. The door image does
not change; only the light does.

## Decisions already made

| Topic | Decision |
|---|---|
| Daytime | The frontlight stays on during the day (the door must be readable in a dark hallway). |
| Period | One "off from HH:MM to HH:MM" period, the same every day, independent of the workday. |
| Level after the night | The level the Kindle had before the light went off. No configurable level. |
| Who decides | The server (it knows the time zone and the admin can edit the schedule); the Kindle obeys a response header. |
| Default | Off. Nothing changes for anyone who does not set the schedule. |

Out of scope (YAGNI): a configurable brightness, per-weekday schedules, a different image at
night, and the Kindle falling back to its own clock when the server is unreachable.

## Configuration

Two optional keys in `[display]`, in 24-hour `HH:MM`, read in `display.timezone`:

```toml
[display]
light_off = "22:00"   # turn the Kindle's frontlight off at this time...
light_on = "07:00"    # ...and back on (to its previous level) at this time
```

- Both absent: the feature is off (the default; `DISPLAY_DEFAULTS` gets no entry for them).
- Validation in `config.validate` raises `ConfigInvalid` (new translated keys under
  `config_error`) when only one of them is set, when a value is not a string matching
  `^([01][0-9]|2[0-3]):[0-5][0-9]$`, or when both are equal.
- The period may cross midnight (`22:00` → `07:00`) or not (`13:00` → `14:00`).
- Strings rather than TOML local times: `22:00` without seconds is not valid TOML 1.0, and a
  hand-edited file should accept what people naturally type.

## Server

### `src/inkdoor/light.py` (new, pure)

- `light_state(now: datetime, cfg: dict) -> str`: `"off"` when the local wall time of `now` (in
  `display.timezone`) is inside `[light_off, light_on)`, else `"on"`. `"on"` when the feature is
  not configured.
- `next_light_change(now: datetime, cfg: dict) -> datetime | None`: the next moment after `now`
  at which `light_state` changes (today's or tomorrow's `light_off`/`light_on`, in local time).
  `None` when the feature is not configured.
- Both work on local wall time, so a daylight-saving change never shifts the period. When a
  boundary falls in a skipped hour, the change happens at the transition.

`render.py` and `render.next_change` do not change: the image is the same at night.

### `/kindle.png`

- New header `X-Inkdoor-Light: on|off` on every successful image response, computed from
  `light_state(now, state.cfg)`, including the "data too old" image (the light depends only on the
  clock). It is `on` both outside the period **and when the feature is not configured**, so turning
  the feature off in the middle of the night brings the light back at the next fetch instead of
  leaving it off for good.
- Not sent with the 503 "not rendered yet" text or the rejected-host image: the Kindle only acts on
  the light after a valid image download, and a request the server rejects should change nothing.
  Defensively, it is not sent when `state.cfg` is not a dict (`state.cfg` is otherwise always a
  validated config, the last valid one or the defaults).
- `X-Inkdoor-Next` becomes the smaller of the current wait and the seconds until
  `next_light_change` plus `NEXT_MARGIN`, so the Kindle comes back just after 22:00 instead of up
  to `INTERVAL` later. When `state.next_render_at` is `None` but a light change is ahead, the header
  carries the light wait alone. `NEXT_MAX` still caps it.
- Privacy: the header says only whether the light is on now, not the schedule. `/kindle.png` is
  already public on the LAN and shows the same door. No secret is involved.

### Compatibility

- An older server sends no `X-Inkdoor-Light`: the new Kindle scripts leave the light alone.
- An older Kindle ignores the extra header (the existing rule: extra headers are ignored).

## Kindle scripts

### `kindle/inkdoor/common.sh`

- `BACKLIGHT=/sys/class/backlight` and `LIGHT_SAVED="$DIR/light-saved"` near the other paths (the
  tests redirect both).
- New `apply_light`, reading `X-Inkdoor-Light` from `$HEADERS` case-insensitively, the same way
  `next_wait` reads `X-Inkdoor-Next` (curl and `wget -S` header formats):
  - `off`:
    1. if `$LIGHT_SAVED` does not exist, read `lipc-get-prop com.lab126.powerd flIntensity`. Only
       if the answer is a whole number, write it to `$LIGHT_SAVED` and log
       `light off (saved level N)`; otherwise stop here and leave the light alone, since a light
       turned off without a saved level could never be restored;
    2. `lipc-set-prop com.lab126.powerd flIntensity 0`;
    3. then write `0` to every writable `$BACKLIGHT/*/brightness`. On some models level 0 through
       `lipc` still leaves a faint glow; the sysfs write turns the LEDs fully off. `lipc` goes first
       so `powerd` also believes the level is 0, and restoring later is a real change for it.

    Repeated on every fetch during the night: cheap and idempotent.
  - `on`: if `$LIGHT_SAVED` holds a whole number, `lipc-set-prop com.lab126.powerd flIntensity N`;
    only when that succeeds, remove the file and log `light on (level N)` (a failure keeps the file
    for the next fetch). A file with anything else is removed without changing the light. No file: nothing happens, so users who never set a schedule see no
    difference.
  - No header or any other value: nothing happens.
- Kindles without a frontlight: `lipc-get-prop` fails, so nothing is saved or written.
- `$LIGHT_SAVED` lives on the Kindle's user storage (`/mnt/us/inkdoor`), not in `/tmp`: if the
  Kindle reboots during the night, `powerd` may have stored 0 as its preference, and the saved
  daytime level must survive the reboot.
- Log lines are written only at the two transitions, not on every fetch, to keep `log.txt` small.
  They are developer-facing log text like the existing `log` calls, not screen messages.

### `kindle/inkdoor/loop.sh`

Calls `apply_light` right after a successful `download`, before drawing the image.

### Versioning

`kindle_files.KINDLE_VERSION` goes to `(1, 3, 0)` and `SCRIPTS_SHA256` is updated. The KPM
uninstall hook already removes `/mnt/us/inkdoor`, including `light-saved`; it needs no change.

### Accepted edge case

If the Kindle is restarted at night to use it normally, its frontlight may be at 0 and the user
raises it by hand. If inkdoor later runs during the day, it restores the level saved before that
night. Rare, and harmless.

## Web admin

On the Screen page (`web/screen.py`, `templates/screen.html`, `web/forms.py`), a new "Kindle light"
fieldset after the workday settings:

- a checkbox "Turn the light off at night" (`light_enabled`);
- two `<input type="time">` fields, "Off at" (`light_off`) and "On at" (`light_on`). When the file
  has no schedule they are prefilled with `22:00` and `07:00` as a suggestion, written only if the
  box is checked;
- a short help text: it needs the Kindle scripts 1.3.0 or newer (updated through KPM), and the
  light returns to the level it had before.

`forms.screen_form` validates them when the box is checked (both required, `HH:MM`, different) with
translated errors. `_apply_screen` writes both keys when the box is checked and removes both when it
is not; the rest of the page keeps its "do not write unchanged defaults" behavior.

## Internationalization and docs

- New keys in `src/inkdoor/locales/en-US.json` and `pt-BR.json` (admin labels, help, form errors,
  `config_error` entries). `tests/test_i18n.py` keeps the catalogs in sync.
- `docs/kindle.md` and `docs/pt-BR/kindle.md`: what the schedule does, that the previous level
  comes back in the morning, the Kindle version it needs, and that the light stays as it is while
  the server is unreachable.
- The `[display]` row of the key table in `README.md` and `README.pt-BR.md`.
- `config.example.toml`: both keys, commented out.
- `CHANGELOG.md`: a line under `## [Unreleased]`.

## Testing

Python (`pytest`):

- `light.py`: inside and outside a period that crosses midnight and one that does not; exactly at
  each boundary (`light_off` is inside, `light_on` is outside); not configured; `next_light_change`
  today and tomorrow; a daylight-saving change day in a zone that has one (e.g.
  `America/New_York`).
- `config.validate`: only one key, bad formats (`"7:00"`, `"24:00"`, `"22:00:00"`, a number),
  equal times; valid values pass.
- `/kindle.png`: `off` inside the period, `on` outside it, `on` when not configured, the header on
  the stale image, no header on the 503 and on the rejected-host image, and `X-Inkdoor-Next`
  shortened near a boundary (and present when only a light change is ahead).
- Admin: the Screen form round trip (enable, edit, disable removes both keys, validation errors).
- `kindle_files`: the version and hash test.

Shell (`tests/test_kindle_scripts.py`, stub `lipc-get-prop`/`lipc-set-prop` on `PATH`, `BACKLIGHT`
and `LIGHT_SAVED` redirected into `tmp_path`):

- `off` saves the level once and sets 0 through lipc and sysfs; a second `off` keeps the first
  saved level;
- `on` restores the saved level and removes the file; `on` without a file does nothing; a failing
  `lipc-set-prop` keeps the file;
- no header, an unknown value, a non-numeric `lipc-get-prop` answer and a missing `lipc` change
  nothing and save nothing (in particular, `off` does not turn the light off without a saved
  level);
- both header formats (curl, `wget -S`).

ShellCheck on `kindle/` as in CI.

### Hardware

The tests cannot show that `flIntensity 0` plus the sysfs write really turns the LEDs off, or that
the level comes back, on a given model. The PR's test plan gets an item for the maintainer to check
on a real Kindle (off at the start of the period, on at its end, the previous level restored, and
after a reboot during the night). If that check is still pending when the PR merges, an issue with
`status: needs hardware` tracks it.

## Tracking

An issue (`type: feature`, `priority: medium`, `area: server`, `area: kindle`, `area: admin`)
describes the feature before the PR; the PR says "Fixes #N".
