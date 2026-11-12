# Kindle Night Light Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Kindle's frontlight off during a configured period every day and restore its previous level afterwards.

**Architecture:** A pure `inkdoor.light` module decides "on"/"off" from `[display] light_off`/`light_on` in the display time zone. `/kindle.png` sends it as `X-Inkdoor-Light` and shortens `X-Inkdoor-Next` before each boundary. The Kindle's `apply_light` saves the level on "off", turns the light off through `lipc` and sysfs, and restores the level on "on". The admin's Screen page edits the two keys.

**Tech Stack:** Python 3.10+ (Flask, zoneinfo, pytest), POSIX sh (BusyBox), ShellCheck.

**Spec:** `docs/superpowers/specs/2026-11-11-kindle-night-light-design.md`

## Global Constraints

- Everything in the repo is English; user-visible strings go through `en-US.json` and `pt-BR.json` (same keys, `tests/test_i18n.py`).
- Config keys: `[display] light_off`, `light_on`, strings matching `^([01][0-9]|2[0-3]):[0-5][0-9]$` (full match), both or neither, never equal. No entry in `DISPLAY_DEFAULTS`.
- Off period is `[light_off, light_on)` in local wall time of `display.timezone`; it may cross midnight.
- Header: `X-Inkdoor-Light: on|off` (lowercase values), only on successful `/kindle.png` image responses; `on` when the feature is not configured.
- `X-Inkdoor-Next` = min(render wait, seconds to next light change + `NEXT_MARGIN`), capped by `NEXT_MAX`.
- Kindle: `LIGHT_SAVED="$DIR/light-saved"`, `LIGHT_NODES="/sys/devices/system/fl_tps6116x/fl_tps6116x0/fl_intensity /sys/class/backlight/max77696-bl/brightness"` (a fixed list, never a glob); `lipc-get-prop com.lab126.powerd flIntensity` / `lipc-set-prop com.lab126.powerd flIntensity N`. POSIX sh, ShellCheck-clean with `kindle/.shellcheckrc`; `apply_light` variables start with `light_` and every path returns 0.
- `KINDLE_VERSION = (1, 3, 0)` and a matching `SCRIPTS_SHA256`.
- Config errors never echo the value (a misplaced link must never be repeated back), and name the key in a `field=` detail: `key=` clashes with `Translator.__call__(self, key, **kwargs)` (`i18n.py:61`) and raises `TypeError`.
- Upgrade instructions say `;kpm update`, then `;kpm upgrade` (as `MSG_KPM_OK` does).
- Python commands use the uv-made `.venv` (system Python is 3.9): `.venv/bin/pytest`.

## Review Focus

1. Kindle rebooted during the night: `powerd` now reports level 0, the saved file still holds the day level; a second `off` must keep the saved level and the morning `on` must restore it (test in Task 3).
2. Hand-edited config with a TOML local time (`light_off = 22:00:00`) or a number (`light_off = 22`): a translated config error, never a crash (test in Task 1).
3. Server running in a different time zone from `display.timezone`: the state follows `display.timezone`, given a UTC `now` (test in Task 1).
4. Admin: box checked with an empty time field: a field error and no write (test in Task 4).
5. Admin: box unchecked while a time field holds garbage: the save still goes through and removes both keys (test in Task 4).

---

### Task 1: Schedule logic and config validation

**Files:**
- Create: `src/inkdoor/light.py`
- Modify: `src/inkdoor/config.py` (`validate`)
- Modify: `src/inkdoor/locales/en-US.json`, `src/inkdoor/locales/pt-BR.json` (`config_error`)
- Test: `tests/test_light.py` (new), `tests/test_config.py`

**Interfaces:**
- Produces (in `inkdoor.light`):
  - `parse_time(value) -> datetime.time | None`: the time for a valid `"HH:MM"` string, else `None` (any non-string, `"7:00"`, `"24:00"`, `"22:00:00"`).
  - `schedule(cfg: dict) -> tuple[datetime.time, datetime.time] | None`: `(off, on)` when both `cfg["display"]` keys parse, else `None`.
  - `light_state(now: datetime.datetime, cfg: dict) -> str`: `"off"` or `"on"`; `now` is aware, in any zone.
  - `next_light_change(now: datetime.datetime, cfg: dict) -> datetime.datetime | None`: aware, in `display.timezone`.

- [ ] **Step 1: Write the failing tests in `tests/test_light.py`**

Helpers: `cfg(off="22:00", on="07:00", tz="America/Sao_Paulo")` builds `{"display": {"timezone": tz, "light_off": off, "light_on": on}}` (omitting `None` values); `at(y, m, d, h, mi, tz)` builds an aware datetime.

```python
@pytest.mark.parametrize("hm, expected", [
    ((21, 59), "on"), ((22, 0), "off"), ((23, 30), "off"), ((0, 0), "off"),
    ((6, 59), "off"), ((7, 0), "on"), ((12, 0), "on"),
])
def test_period_across_midnight(hm, expected):
    assert light_state(at(2026, 11, 11, *hm, SP), cfg()) == expected

@pytest.mark.parametrize("hm, expected", [((12, 59), "on"), ((13, 0), "off"), ((14, 0), "on")])
def test_period_within_a_day(hm, expected):
    assert light_state(at(2026, 11, 11, *hm, SP), cfg("13:00", "14:00")) == expected

def test_not_configured_is_on_with_no_change():
    for c in ({"display": {"timezone": SP}}, cfg(on=None)):
        assert light_state(at(2026, 11, 11, 23, 0, SP), c) == "on"
        assert next_light_change(at(2026, 11, 11, 23, 0, SP), c) is None

def test_state_follows_the_display_time_zone():                     # Review Focus 3
    now = dt.datetime(2026, 11, 12, 1, 30, tzinfo=dt.timezone.utc)  # 22:30 in Sao Paulo
    assert light_state(now, cfg()) == "off"
    assert light_state(now, cfg(tz="Europe/Lisbon")) == "off"       # 01:30 in Lisbon
    assert light_state(now, cfg(tz="Asia/Tokyo")) == "on"           # 10:30 in Tokyo

def test_next_change_today_and_tomorrow():
    assert next_light_change(at(2026, 11, 11, 12, 0, SP), cfg()) == at(2026, 11, 11, 22, 0, SP)
    assert next_light_change(at(2026, 11, 11, 22, 0, SP), cfg()) == at(2026, 11, 12, 7, 0, SP)
    assert next_light_change(at(2026, 11, 11, 23, 0, SP), cfg()) == at(2026, 11, 12, 7, 0, SP)

def test_next_change_across_a_daylight_saving_night():
    ny = "America/New_York"                                          # springs forward 2026-03-08
    now = at(2026, 3, 7, 23, 0, ny)
    change = next_light_change(now, cfg(tz=ny))
    assert change == at(2026, 3, 8, 7, 0, ny)
    assert change.timestamp() - now.timestamp() == 7 * 3600         # one hour was skipped

@pytest.mark.parametrize("value", ["7:00", "24:00", "22:00:00", "", "22h", 22,
                                   dt.time(22, 0), None, "22:00\n", "２２:００"])
def test_parse_time_refuses_anything_but_hh_mm(value):
    assert parse_time(value) is None
```

- [ ] **Step 2: Add the failing config tests to `tests/test_config.py`**

Extend `test_invalid_values_are_explained`'s parameter list (key = the `ConfigInvalid.key`):

```python
    ('[display]\nlight_off = "22:00"\n', "light_pair"),
    ('[display]\nlight_on = "07:00"\n', "light_pair"),
    ('[display]\nlight_off = "7:00"\nlight_on = "07:00"\n', "light_time"),
    ('[display]\nlight_off = 22:00:00\nlight_on = "07:00"\n', "light_time"),   # Review Focus 2
    ('[display]\nlight_off = 22\nlight_on = "07:00"\n', "light_time"),          # Review Focus 2
    ('[display]\nlight_off = "22:00"\nlight_on = "22:00"\n', "light_same"),
```

and a passing case plus a message check:

```python
def test_light_schedule_loads(tmp_path):
    cfg = config.load(write(tmp_path, '[display]\nlight_off = "22:00"\nlight_on = "07:00"\n'))
    assert (cfg["display"]["light_off"], cfg["display"]["light_on"]) == ("22:00", "07:00")

@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_light_errors_do_not_echo_the_value(tmp_path, language):
    secret = "https://calendar.example/private-not-real.ics"
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, f'[display]\nlight_off = "{secret}"\nlight_on = "07:00"\n'))
    message = Translator(language)(f"config_error.{err.value.key}", **err.value.details)
    assert secret not in message and "light_off" in message and "{" not in message
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_light.py tests/test_config.py -q`
Expected: FAIL (`ModuleNotFoundError: inkdoor.light`, and the new config cases not raised).

- [ ] **Step 4: Implement `inkdoor.light` and the validation**

- `light.py` imports nothing from the package; it reads `cfg["display"]["timezone"]` through `ZoneInfo` and converts `now` with `astimezone`. `parse_time` uses `re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", value)` on `str` values only.
- `light_state`: compare `local.time()` (seconds and microseconds dropped) with `(off, on)`: `off <= t < on` when `off < on`, else `t >= off or t < on`.
- `next_light_change`: candidates `datetime.combine(day, t, tz)` for `day` in local today and tomorrow, `t` in `(off, on)`; return the one with the smallest `.timestamp()` that is greater than `now.timestamp()`.
- `config.validate`, after the workday checks: if either key is present, raise `ConfigInvalid("light_pair")` unless both are; `ConfigInvalid("light_time", field=<key>)` for the first that does not parse; `ConfigInvalid("light_same")` when equal.
- Catalog entries under `config_error`:
  - en-US: `"light_time": "{field} must be a 24-hour time like \"22:00\", from 00:00 to 23:59."`, `"light_pair": "light_off and light_on must be set together."`, `"light_same": "light_off and light_on must be different times."`
  - pt-BR: `"light_time": "{field} precisa ser um horário de 24 horas como \"22:00\", de 00:00 a 23:59."`, `"light_pair": "light_off e light_on precisam ser definidos juntos."`, `"light_same": "light_off e light_on precisam ser horários diferentes."`

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_light.py tests/test_config.py tests/test_i18n.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/inkdoor/light.py src/inkdoor/config.py src/inkdoor/locales tests/test_light.py tests/test_config.py
git commit -m "Add the night light schedule and its config keys"
```

---

### Task 2: Light header on `/kindle.png`

**Files:**
- Modify: `src/inkdoor/web/__init__.py` (constants near `NEXT_HEADER`; the `kindle()` route)
- Test: `tests/test_web_core.py`

**Interfaces:**
- Consumes: `light.light_state`, `light.next_light_change` (Task 1).
- Produces: `LIGHT_HEADER = "X-Inkdoor-Light"` in `inkdoor.web`.

- [ ] **Step 1: Write the failing tests**

Helpers: `def epoch(y, m, d, h, mi, tz="America/Sao_Paulo") -> float` (timestamp of that local time) and `def at_time(clock, rendered, when)`, which sets `clock.now = when` and `os.utime(rendered, (when, when))` so `state.image_stale` never depends on the real date. Each test sets `state.cfg["display"].update(light_off="22:00", light_on="07:00")` where needed and moves the clock only through `at_time`. (The snippets below write `clock.now = ...` for short; use `at_time`.)

```python
def test_kindle_png_turns_the_light_off_at_night(app, state, clock, rendered):
    state.cfg["display"].update(light_off="22:00", light_on="07:00")
    clock.now = epoch(2026, 11, 11, 23, 0)
    assert get(client(app), "/kindle.png").headers["X-Inkdoor-Light"] == "off"
    clock.now = epoch(2026, 11, 12, 7, 0)
    assert get(client(app), "/kindle.png").headers["X-Inkdoor-Light"] == "on"

def test_kindle_png_says_on_when_the_schedule_is_not_set(app, clock, rendered):
    clock.now = epoch(2026, 11, 11, 23, 0)
    assert get(client(app), "/kindle.png").headers["X-Inkdoor-Light"] == "on"

def test_kindle_png_comes_back_right_after_a_light_change(app, state, clock, rendered):
    state.cfg["display"].update(light_off="22:00", light_on="07:00")
    clock.now = epoch(2026, 11, 11, 21, 58)                          # 120 s before 22:00
    assert get(client(app), "/kindle.png").headers["X-Inkdoor-Next"] == "125"   # light only
    state.next_render_at, state.render_seconds = clock.now + 600, 0
    assert get(client(app), "/kindle.png").headers["X-Inkdoor-Next"] == "125"   # sooner wins
    state.next_render_at = clock.now + 60
    assert get(client(app), "/kindle.png").headers["X-Inkdoor-Next"] == "65"

def test_light_header_only_on_real_images(app, state, clock, rendered):
    state.cfg["display"].update(light_off="22:00", light_on="07:00")
    clock.now = epoch(2026, 11, 11, 23, 0)
    assert "X-Inkdoor-Light" not in get(client(app), "/kindle.png",
                                        headers={"Host": "evil.com"}).headers
    rendered.unlink()
    assert "X-Inkdoor-Light" not in get(client(app), "/kindle.png").headers    # the 503
```

```python
def test_a_light_bug_never_stops_the_door(app, state, clock, rendered, monkeypatch):
    def boom(*_):
        raise RuntimeError("bug")
    monkeypatch.setattr(light, "light_state", boom)
    r = get(client(app), "/kindle.png")
    assert r.status_code == 200 and r.data == rendered.read_bytes()
    assert "X-Inkdoor-Light" not in r.headers
```

Also add a sibling of `test_kindle_png_is_replaced_when_the_render_loop_is_stuck` showing that the stale image response still carries `X-Inkdoor-Light`. `test_kindle_png_says_when_to_come_back` stays green: no schedule means no light wait. (The rejected-host and 503 assertions already pass before the change; they guard against regressions.)

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_web_core.py -q -k "light or come_back or door"`
Expected: FAIL (`KeyError: 'X-Inkdoor-Light'`, and `light` has no `light_state` to patch until the import exists).

- [ ] **Step 3: Implement in `kindle()`**

- After the stale check, read `cfg = state.cfg` once. Inside `try:`, `now = dt.datetime.fromtimestamp(clock(), dt.timezone.utc)`, `state_ = light.light_state(now, cfg)`, `change = light.next_light_change(now, cfg)`, then set `headers[LIGHT_HEADER]`. On `except Exception`, log the exception type only (as `_unexpected` does) and go on with no light header and `change = None`. Call through the module (`light.light_state`) so the monkeypatch applies.
- Collect the waits: the existing render wait (when `state.next_render_at` is set) and `max(0.0, change.timestamp() - clock()) + NEXT_MARGIN` (when `change` is set); send `NEXT_HEADER` as `min(NEXT_MAX, math.ceil(min(waits)))` when there is any.
- Update the header comment above `NEXT_HEADER` to mention light changes.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_web_core.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/inkdoor/web/__init__.py tests/test_web_core.py
git commit -m "Tell the Kindle whether its light should be on"
```

---

### Task 3: Kindle scripts obey the header

**Files:**
- Modify: `kindle/inkdoor/common.sh` (paths block; new `apply_light` after `next_wait`)
- Modify: `kindle/inkdoor/loop.sh` (call after a successful download)
- Modify: `src/inkdoor/kindle_files.py` (`KINDLE_VERSION`, `SCRIPTS_SHA256`)
- Test: `tests/test_kindle_scripts.py`

**Interfaces:**
- Consumes: the `X-Inkdoor-Light` header contract (Task 2).
- Produces: `apply_light` (no arguments; reads `$HEADERS`, `$LIGHT_SAVED`, `$LIGHT_NODES`).

- [ ] **Step 1: Write the failing tests**

Extend `run()` to also replace `/sys/` with `f"{tmp_path}/sys/"`. Add a fixture `lipc(tmp_path)` that writes stubs into `tmp_path / "bin"`: `lipc-get-prop` prints the content of `tmp_path / "level"`; `lipc-set-prop` appends `"$*"` to `tmp_path / "calls"` and writes its last argument to `tmp_path / "level"`; a `fail-set` file in `tmp_path` makes `lipc-set-prop` exit 1. A fixture `nodes(tmp_path)` creates, each containing `10`: `sys/class/backlight/max77696-bl/brightness` (PW2/PW3), `sys/devices/system/fl_tps6116x/fl_tps6116x0/fl_intensity` (PW1) and `sys/class/backlight/fp9966-bl0/brightness` (an amber node that must stay untouched). Helper `headers(tmp_path, light)` writes `"HTTP/1.1 200 OK\r\nX-Inkdoor-Light: {light}\r\n\r\n"` to `inkdoor.headers`.

```python
def test_light_off_saves_the_level_once_and_turns_everything_off(tmp_path, lipc, nodes):
    (tmp_path / "level").write_text("12\n"); headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert (tmp_path / "inkdoor" / "light-saved").read_text().strip() == "12"
    assert (tmp_path / "calls").read_text() == "com.lab126.powerd flIntensity 0\n"
    assert read(nodes["pw2"]) == read(nodes["pw1"]) == "0"
    assert read(nodes["amber"]) == "10"

def test_light_off_at_level_0_skips_lipc_but_still_darkens_sysfs(tmp_path, lipc, nodes): ...
    # saved "12" exists, level "0": no calls file, pw2/pw1 nodes "0"

def test_light_off_leaves_sysfs_alone_when_lipc_fails(tmp_path, lipc, nodes): ...
    # level "12", fail-set present: light-saved holds 12, every node still "10"

def test_a_night_reboot_keeps_the_day_level(tmp_path, lipc):                 # Review Focus 1
    (tmp_path / "inkdoor").mkdir(); (tmp_path / "inkdoor" / "light-saved").write_text("12\n")
    (tmp_path / "level").write_text("0\n"); headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert (tmp_path / "inkdoor" / "light-saved").read_text().strip() == "12"
    headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert (tmp_path / "level").read_text().strip() == "12"
    assert not (tmp_path / "inkdoor" / "light-saved").exists()

def test_light_on_without_a_saved_level_changes_nothing(tmp_path, lipc):
    (tmp_path / "level").write_text("12\n"); headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not (tmp_path / "calls").exists()

def test_light_on_keeps_the_saved_level_when_lipc_fails(tmp_path, lipc):
    ...  # saved "12", fail-set present, "on" -> light-saved still holds 12

@pytest.mark.parametrize("raw", [
    "HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n",       # an older server
    "HTTP/1.1 200 OK\r\nX-Inkdoor-Light: dim\r\n\r\n",
])
def test_light_ignores_missing_or_unknown_headers(tmp_path, lipc, raw): ...
    # no calls, brightness still 10, no light-saved

@pytest.mark.parametrize("answer", ["", "abc"])
def test_light_off_without_a_readable_level_changes_nothing(tmp_path, lipc, answer): ...

def test_light_off_without_lipc_changes_nothing(tmp_path): ...               # no stubs on PATH

@pytest.mark.parametrize("raw", [
    "HTTP/1.1 200 OK\r\nx-inkdoor-light: off\r\n\r\n",          # any case
    "  HTTP/1.1 200 OK\n  X-Inkdoor-Light: off\n",                # wget -S indents headers
])
def test_light_reads_both_header_formats(tmp_path, lipc, raw): ...           # level saved, 0 set
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_kindle_scripts.py -q`
Expected: FAIL (`apply_light: not found`).

- [ ] **Step 3: Implement `apply_light` in `common.sh`**

- Read the value like `next_wait` does, keeping only `[a-z]` after the header name: `sed -n 's/^[[:space:]]*[Xx]-[Ii]nkdoor-[Ll]ight:[[:space:]]*\([a-z]*\).*/\1/p' "$HEADERS" 2>/dev/null | tail -n 1`.
- `off`, `on` and everything else as in the spec's "Kindle scripts" section: on `off`, read the level and save it when there is no saved file, stopping when the level is not a whole number (`case ... in ''|*[!0-9]*)`); `lipc-set-prop ... 0` only when the level is not 0, stopping if it fails; then `for light_node in $LIGHT_NODES; do` skipping nodes that are not writable or already read `0` (`[ -w "$light_node" ] || continue`). On `on`, remove the file only after `lipc-set-prop` succeeds; a non-numeric file is removed.
- Variables start with `light_` and every exit path is `return 0` (the test helper runs with `check=True`; a bare `return` after a failed command returns its status).
- Log only on the two transitions: `log "light off (saved level $n)"`, `log "light on (level $n)"`.
- Discard `lipc` stderr (`2>/dev/null`) so a Kindle without a frontlight logs nothing.
- `loop.sh`: `apply_light` right after `if ensure_wifi && download; then`.

- [ ] **Step 4: Bump the Kindle version**

Set `KINDLE_VERSION = (1, 3, 0)`, then put the output of
`.venv/bin/python -c "from inkdoor import kindle_files as k; print(k.scripts_digest(k.find_dir()))"`
into `SCRIPTS_SHA256`.

- [ ] **Step 5: Run the tests and ShellCheck**

Run: `.venv/bin/pytest tests/test_kindle_scripts.py tests/test_kindle_files.py -q && (cd kindle && shellcheck inkdoor/*.sh documents/*.sh kpm/*.sh)`
Expected: PASS, no ShellCheck output.

- [ ] **Step 6: Commit**

```bash
git add kindle/inkdoor src/inkdoor/kindle_files.py tests/test_kindle_scripts.py
git commit -m "Turn the Kindle's light off when the server says so"
```

---

### Task 4: Screen page in the admin

**Files:**
- Modify: `src/inkdoor/web/forms.py` (`screen_form`)
- Modify: `src/inkdoor/web/screen.py` (`_screen_values`, `_apply_screen`, `LIGHT_SUGGESTED`)
- Modify: `src/inkdoor/web/templates/screen.html` (fieldset after the workdays fieldset)
- Modify: `src/inkdoor/locales/en-US.json`, `src/inkdoor/locales/pt-BR.json` (`admin`)
- Test: `tests/test_web_pages.py`

**Interfaces:**
- Consumes: `light.parse_time` (Task 1).
- Produces: form fields `light_enabled` (checkbox, value `"1"`), `light_off`, `light_on`; `values["light_enabled"]: bool`, `values["light_off"]`, `values["light_on"]: str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_screen_light_schedule_round_trip(logged, state):
    page = body(logged.get("/screen"))
    assert EN("admin.field_light") in page and 'value="22:00"' in page   # suggestion, unchecked
    assert not re.search(r'name="light_enabled"[^>]*checked', page)
    logged.post("/screen", data=screen_form(logged, light_enabled="1",
                                            light_off="23:30", light_on="06:45"))
    assert logged.raw() == {"display": {"light_off": "23:30", "light_on": "06:45"}}
    assert re.search(r'name="light_enabled"[^>]*checked', body(logged.get("/screen")))
    logged.post("/screen", data=screen_form(logged))                      # unchecked
    assert logged.raw() == {"display": {}}

def test_screen_unchecked_light_ignores_its_fields(logged, state):       # Review Focus 5
    write_config(state, '[display]\nlight_off = "22:00"\nlight_on = "07:00"\n')
    r = logged.post("/screen", data=screen_form(logged, light_off="https://x.example/a.ics"))
    assert r.status_code == 303 and logged.raw() == {"display": {}}
```

and add to `test_screen_tampered_values_show_field_errors`'s list:

```python
    ({"light_enabled": "1", "light_off": "", "light_on": "07:00"}, "light_off",
     "admin.error_light_time"),                                          # Review Focus 4
    ({"light_enabled": "1", "light_off": "22:00", "light_on": "25:00"}, "light_on",
     "admin.error_light_time"),
    ({"light_enabled": "1", "light_off": "07:00", "light_on": "07:00"}, "light_on",
     "admin.error_light_same"),
```

`test_screen_save_of_the_defaults_pins_nothing` must stay green (no box, nothing written).

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_web_pages.py -q -k screen`
Expected: FAIL

- [ ] **Step 3: Implement**

- `screen_form`: `values["light_enabled"] = _text(form, "light_enabled") == "1"`. For each time field, keep the text only when `parse_time` accepts it (else `""`, so nothing pasted is shown back). When enabled: an invalid one gets `t("admin.error_light_time")`; both valid and equal sets `errors["light_on"] = t("admin.error_light_same")`.
- `screen.py`: `LIGHT_SUGGESTED = ("22:00", "07:00")`. `_screen_values` sets `light_enabled` when both keys are in `[display]`, and each time from the file when `parse_time` accepts it, else the suggestion. `_apply_screen`, after the existing loop: when enabled, write both keys into `data.setdefault("display", {})`; otherwise pop both from an existing `[display]` table.
- Template: a `<fieldset class="field">` with legend `admin.field_light`, a `label.choice` checkbox `light_enabled` (`admin.field_light_enabled`), a `field-pair` of `m.text_field(..., type="time")` for `light_off` / `light_on`, and `<p class="help">` with `admin.field_light_help`.
- `admin` catalog keys:

| Key | en-US | pt-BR |
|---|---|---|
| `field_light` | Kindle light | Luz do Kindle |
| `field_light_enabled` | Turn the light off at night | Apagar a luz à noite |
| `field_light_off` | Off at | Apagar às |
| `field_light_on` | On at | Acender às |
| `field_light_help` | Turns the Kindle's frontlight off between these times, then brings it back to the level it had. Needs the Kindle scripts 1.3 or newer (;kpm update, then ;kpm upgrade). | Apaga a luz frontal do Kindle entre esses horários e depois volta ao nível que ela tinha. Precisa dos scripts do Kindle 1.3 ou mais novos (;kpm update e depois ;kpm upgrade). |
| `error_light_time` | Enter a valid time. | Digite um horário válido. |
| `error_light_same` | The light must go off and on at different times. | A luz precisa apagar e acender em horários diferentes. |

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_web_pages.py tests/test_i18n.py -q`
Expected: PASS

- [ ] **Step 5: Look at the page in both languages**

Start the admin on a scratch config (`INKDOOR_CONFIG=<scratch>/config.toml`, admin enabled) and open `/screen` in the browser pane in en-US and pt-BR, at desktop and phone width. Check that the fieldset lines up with the workday fields and that the help text wraps cleanly.

- [ ] **Step 6: Commit**

```bash
git add src/inkdoor/web src/inkdoor/locales tests/test_web_pages.py
git commit -m "Edit the night light schedule on the Screen page"
```

---

### Task 5: Docs and changelog

**Files:**
- Modify: `docs/kindle.md`, `docs/pt-BR/kindle.md` (a "Dark at night" / "Escuro à noite" bullet in Tips)
- Modify: `README.md`, `README.pt-BR.md` (`[display]` row: add `light_off`, `light_on`)
- Modify: `config.example.toml` (both keys commented under `min_gap_minutes`)
- Modify: `CHANGELOG.md` (`## [Unreleased]` → `### Added`)
- Modify: `CLAUDE.md` ("Conventions": the `/kindle.png` header bullet also names `X-Inkdoor-Light`, sent as `on` when no schedule is set, ignored by older Kindles)
- Modify: any other page that lists the Screen page settings (`grep -rn "min_gap_minutes\|refresh_minutes" docs README*`)

- [ ] **Step 1: Write the docs**

The Tips bullet says: the e-ink panel gives no light, only the frontlight does; set the off/on times on the admin's Screen page (or `light_off`/`light_on`); in the morning the light returns to the level it had; it needs the Kindle scripts 1.3 (`;kpm update`, then `;kpm upgrade`, or a new zip); while the server is unreachable the light stays as it is; if the Kindle is restarted or inkdoor uninstalled at night, raise the light by hand. en-US text writes times as 10:00 PM / 7:00 AM (config values stay `"22:00"`); pt-BR uses 22:00 / 07:00. `config.example.toml`:

```toml
# light_off = "22:00"       # turn the Kindle's frontlight off at this time (24-hour HH:MM)...
# light_on = "07:00"        # ...and back to its previous level at this time
```

CHANGELOG line: `- An optional schedule turns the Kindle's frontlight off at night and brings it back to its previous level in the morning (Screen page, or \`light_off\`/\`light_on\` in \`[display]\`). Needs the Kindle scripts 1.3.0.`

- [ ] **Step 2: Check the example config still loads and the docs match**

Run: `.venv/bin/pytest -q`
Expected: PASS (the example config is loaded by the tests). Compare each English page with its pt-BR translation for the same bullets.

- [ ] **Step 3: Commit**

```bash
git add docs README.md README.pt-BR.md config.example.toml CHANGELOG.md CLAUDE.md
git commit -m "Document the night light"
```

---

### Task 6: Ship

- [ ] **Step 1: Full verification**

Run: `.venv/bin/pytest -q && (cd kindle && shellcheck inkdoor/*.sh documents/*.sh kpm/*.sh)`
Expected: all tests pass, no ShellCheck output.

- [ ] **Step 2: Issue**

With the maintainer's OK, search (`gh issue list --state all --search "light"`), then open "Turn the Kindle's light off at night" with `type: feature`, `priority: medium`, `area: server`, `area: kindle`, `area: admin` (body: context, behavior, acceptance criteria, files). No private data.

- [ ] **Step 3: Review loop**

`git fetch`, then `/code-review high origin/master...HEAD`; handle every finding (fix, not applicable, or an issue); review the fix commits with `/code-review high <last-reviewed>..HEAD` until a round is clean. Stop and ask after a fourth round that still finds a real defect.

- [ ] **Step 4: Pull request**

Push the branch and open the PR with `.github/pull_request_template.md`: summary, "Fixes #N", the test plan with the `/code-review` totals, and an unchecked hardware item: "On a real Kindle (model: ...): `lipc` still answers after the display starts, the light goes off fully at `light_off`, comes back to the previous level at `light_on`, and still comes back after a reboot during the night." If that stays unchecked at merge, open an issue with `status: needs hardware`.
