# Admin Redesign ("Ink and Paper") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web admin one visual language, one control per kind of value, safer actions and a Home page that is a dashboard of the door, without changing the frontend stack.

**Architecture:** New CSS tokens and a set of Jinja macros carry the look; every page is rebuilt from those macros. The Screen form keeps posting the values `forms.screen_form` already validates. Home reads new in-memory records that the render loop fills (`RenderInfo.sources`, `.timeline`, `.next_word`) and one timestamp the `/kindle.png` handler sets.

**Tech Stack:** Python 3.10+ (Flask, Jinja, pytest), one `admin.css`, one `admin.js` (ES5, optional), inline SVG.

**Spec:** `docs/superpowers/specs/2026-11-12-admin-redesign-design.md`

**Delivery:** four parts, one issue and one pull request each, merged in order. Each part starts from an up-to-date `master` on its own branch and follows "Pull requests" in `CLAUDE.md` (the `/code-review high origin/master...HEAD` loop, the PR template, a `CHANGELOG.md` line under `## [Unreleased]`).

| Part | Issue | Branch | Tasks |
|---|---|---|---|
| 1 | frkey/inkdoor#117 | `feat/admin-shell` | 1, 2 |
| 2 | frkey/inkdoor#118 | `feat/admin-screen-page` | 3, 4 |
| 3 | frkey/inkdoor#119 | `feat/admin-source-lists` | 5, 6 |
| 4 | frkey/inkdoor#120 | `feat/admin-home-dashboard` | 7, 8, 9 |

## Global Constraints

- Flask + Jinja + one `admin.css` + one `admin.js`. No build step, framework, new dependency or CDN.
- The Content-Security-Policy does not change: no `style=` attribute, no `<style>`, no inline script or handler in any template. Per-item geometry is inline `<svg>` with geometry attributes.
- Every page works without `admin.js`. `admin.js` stays ES5 (`var`, no arrow functions), like the file today.
- Routes, form field names, the config file format and the Kindle side do not change. No `KINDLE_VERSION` bump.
- Everything in the repo is English. Visible text goes through the `Translator`; every key exists in both `en-US.json` and `pt-BR.json` (`tests/test_i18n.py`). Times use `Translator.time()` (it prints `8:00`, not `08:00`, in 24-hour mode; keep that), dates `.date_short()`, durations `.duration()`.
- The admin never sends a calendar link, exception text or (on Home) a meeting title to the browser.
- Controls, buttons and button-styled links are at least 44 px tall; text contrast at least 4.5:1 in light and dark.
- Light tokens: `--paper #f4f3f0`, `--surface #ffffff`, `--ink #1d1d1b`, `--ink-contrast #ffffff`, `--muted #5f5e5a`, `--border #dcdad4`, `--border-strong #8a8882`, `--accent #1f4f8a`; keep today's `--ok`, `--warn`, `--fail`, alert and notice colors. In dark mode `--ink` is today's dark `--text` (`#ecebe7`) and `--ink-contrast` today's dark `--bg` (`#161616`).
- Page container: `max-width: 1120px`. Phone breakpoint: `max-width: 640px`.
- The status word uses the bundled `Inter-Black.otf` (weight 900) instead of the spec's 800; add its `@font-face`. No new font file.
- Python commands use the uv-made `.venv`: `.venv/bin/pytest`. JavaScript syntax check: `node --check src/inkdoor/web/static/admin.js`.
- Admin screenshots in `docs/img/` are produced by `scripts/docs_images.py`; rerun it in every part whose page is shown in `README.md` or `docs/server.md` (Home: part 4; Calendars: part 3), for both languages and both themes.

## Review Focus

1. A night light time set by hand off the 30-minute grid (`22:45`): the form shows it selected and a save that does not touch it writes it back unchanged (test in Task 3).
2. A workday ending at 24: the select offers it, labels it as midnight, and it round-trips (test in Task 3).
3. A source that failed but has cached data: Home and Calendars say "old data" with the time of the data, never "up to date"; a busy calendar with no data reads as no data while the door says "Knock first" (tests in Tasks 7 and 9).
4. Events that start before or end after the workday, and all-day events: timeline blocks are clipped to the workday and all-day events are left out (test in Task 8).
5. Nothing configured, or a source named with HTML characters (`<b>&"`): Home renders without the timeline and sources cards, and names are escaped (tests in Task 9).

---

## Part 1: shell and components (frkey/inkdoor#117)

### Task 1: Tokens, shell and the door status chip

**Files:**
- Modify: `src/inkdoor/web/static/admin.css` (tokens, top bar, layout, buttons, inputs, phone rules)
- Modify: `src/inkdoor/web/templates/base.html`
- Create: `src/inkdoor/web/templates/_icons.html`
- Modify: `src/inkdoor/web/__init__.py:356-367` (`_template_globals`)
- Modify: `src/inkdoor/locales/en-US.json`, `pt-BR.json`
- Test: `tests/test_web_core.py`

**Interfaces:**
- Produces: template global `door` (`state.last_render` or `None`), with `.word` and `.headline`.
- Produces: `{% import "_icons.html" as icons %}` and `icons.icon(name)` returning an inline `<svg aria-hidden="true" class="icon">` with `stroke="currentColor"`. Names: `door`, `check`, `warning`, `error`, `up`, `down`, `plus`, `tasks`.
- Produces CSS classes used by later tasks: `.button` (primary), `.button-secondary`, `.button-danger`, `.button-icon`, `.card`, `.page-head`, `.split` (content column plus side column, one column on a phone), `.side` (the side column). `button-quiet` is removed; replace its uses with `button-secondary`.
- New keys: `admin.door_chip_label` ("The door says" / "A porta diz").

- [ ] **Step 1: Write the failing tests** in `tests/test_web_core.py`

```python
def test_every_page_shows_the_door_chip_once_rendered(app, state, rendered):
    c = logged_in(app)
    for path in ("/", "/calendars", "/tasks", "/screen", "/account"):
        page = get(c, path).get_data(as_text=True)
        assert 'class="door-chip"' in page
        assert state.last_render.word in page


def test_no_door_chip_before_the_first_render(app):
    assert 'class="door-chip"' not in get(logged_in(app), "/screen").get_data(as_text=True)


def test_pages_carry_no_inline_style_or_script(app, rendered):
    c = logged_in(app)
    for path in ("/", "/calendars", "/calendars/new", "/tasks", "/screen", "/account"):
        page = get(c, path).get_data(as_text=True)
        assert " style=" not in page and "<style" not in page
        assert re.search(r"<script(?![^>]*\bsrc=)", page) is None
        assert re.search(r"\son[a-z]+=", page) is None
```

- [ ] **Step 2: Run them and see the chip tests fail**

Run: `.venv/bin/pytest tests/test_web_core.py -k "door_chip or inline_style" -v`
Expected: the two chip tests FAIL; the inline-style test passes already and guards the rest of the plan.

- [ ] **Step 3: Implement.** Add `door` to `_template_globals`. In `base.html`: brand with `icons.icon("door")`, the five navigation links unchanged, then `<a class="door-chip" href="/">` holding the status word and `<span class="door-chip-headline">` with the headline (hidden under 900 px), then the logout form with a `button-secondary` button. Replace the token block and add the constraint values above; rename `--bg` to `--paper` and `--text` to `--ink` throughout the file. Inputs and selects: `background: var(--surface)`, `border-color: var(--border-strong)`, `min-height: 44px`. Under 640 px the first row is brand, chip and logout; `.menu` is the second row with `overflow-x: auto; flex-wrap: nowrap`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS.

- [ ] **Step 5: Look at it.** Start the admin with a fictional config in a scratch folder, open every page in en-US and pt-BR, light and dark, at 1280 px and 375 px wide. Nothing clips; the navigation scrolls sideways on the phone.

- [ ] **Step 6: Commit**

```bash
git add src/inkdoor/web src/inkdoor/locales tests/test_web_core.py
git commit -m "Admin: new tokens, shell and a door status chip on every page"
```

### Task 2: Shared macros; restyle login, account, confirm and error

**Files:**
- Modify: `src/inkdoor/web/templates/_macros.html`, `login.html`, `account.html`, `confirm.html`, `error.html`
- Modify: `src/inkdoor/web/static/admin.css`
- Modify: `CHANGELOG.md`
- Test: `tests/test_web_pages.py`

**Interfaces (macros in `_macros.html`; every later task uses exactly these):**
- `time_select(name, label, value, options, errors, described_by=None)`: a labeled `<select>`; `options` is a list of `(value, label)` strings; the option equal to `value` is `selected`.
- `number_field(name, label, value, errors, unit, help=None, min=None, max=None, required=True)`: `<input type="number" inputmode="numeric" class="input-short">` followed by `<span class="unit">{{ unit }}</span>`.
- `segmented(name, legend, value, options, errors)`: a `<fieldset class="segmented">` of radios, each `<label><input type="radio"> <span>label</span></label>`.
- `chips(name, legend, values, options, errors)`: the same with checkboxes in `<fieldset class="chips">`; `values` is the list of checked values.
- `switch(name, label, checked, described_by=None, enables=None)`: `<label class="switch"><input type="checkbox" name value="1"> <span>label</span></label>`; `enables` becomes `data-enables` (a space-separated list of element ids, read by `admin.js` in Task 4).
- `source_state(state, text)`: `<span class="state state-{{ state }}">` with the icon for `ok` (`check`), `stale` (`warning`), `failed` (`error`), `unset` (none) and the text.
- `readonly_row(label, value, help=None)`: a `<dl class="readonly">` row, the value as text.
- `door_preview(token, size, caption=None)`: `<figure class="door-preview">` with the `/kindle.png?t={{ token }}` image (width and height from `size`) inside `<div class="kindle-frame">`, or the "not rendered" text when `token` is none.
- The drawn part of `segmented`, `chips` and `switch` is the `<span>` after a visually hidden input: style `input:checked + span` and `input:focus-visible + span`. The existing `text_field`, `link_field`, `action`, `test_form`, `restore_form`, `config_banners`, `copy_field`, `howto` and `steps` keep their signatures.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_pages.py`

```python
def _macros(app):
    with app.test_request_context("/"):
        return app.jinja_env.get_template("_macros.html").make_module({"t": Translator("en-US")})


def test_time_select_marks_the_current_value(app):
    html = str(_macros(app).time_select("light_off", "Off", "22:30",
                                        [("22:00", "10:00 PM"), ("22:30", "10:30 PM")], {}))
    assert re.search(r'<option value="22:30"\s+selected', html)
    assert html.count("selected") == 1


def test_number_field_shows_the_unit_beside_the_input(app):
    html = str(_macros(app).number_field("refresh_minutes", "Every", 5, {}, "minutes"))
    assert 'class="unit"' in html and ">minutes<" in html and 'value="5"' in html


def test_source_state_is_words_not_color_alone(app):
    html = str(_macros(app).source_state("stale", "Old data"))
    assert "state-stale" in html and "Old data" in html and "<svg" in html


def test_account_page_has_a_single_log_out(logged):
    assert logged.get("/account").get_data(as_text=True).count('action="/logout"') == 1
```

(`logged` and `app` are this file's existing fixtures.)

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/pytest tests/test_web_pages.py -k "time_select or number_field or source_state or single_log_out" -v`
Expected: FAIL (the macros do not exist; Account has two logout forms).

- [ ] **Step 3: Implement** the macros and their CSS. Login, confirm and error: a centered `card narrow` under the brand, one primary button. Account: remove the "This browser" card and put `admin.session_help` as a help line under the password form; "Generate a password" becomes `button-secondary`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS.

- [ ] **Step 5: Changelog.** Under `## [Unreleased]`: "Admin: new look (ink on paper), with the door's status on every page."

- [ ] **Step 6: Commit**

```bash
git add src/inkdoor/web tests/test_web_pages.py CHANGELOG.md
git commit -m "Admin: shared form components; restyle login, account and confirm"
```

---

## Part 2: Screen page (frkey/inkdoor#118)

### Task 3: Time options for the workday and the night light

**Files:**
- Modify: `src/inkdoor/web/screen.py`
- Test: `tests/test_web_pages.py`

**Interfaces:**
- Produces: `hour_options(t: Translator, first: int, last: int) -> list[tuple[str, str]]`: one `(str(hour), label)` per whole hour from `first` to `last` inclusive; the label is `t.time(dt.time(hour % 24))`, so 24 is labeled as midnight.
- Produces: `light_options(t: Translator, current: str) -> list[tuple[str, str]]`: `("HH:MM", t.time(...))` for every 30 minutes from `00:00` to `23:30`; when `current` passes `light.parse_time` and is not on the grid it is added, and the list stays sorted by time.
- `screen_page` passes to the template: `start_hours=hour_options(t(), 0, 23)`, `end_hours=hour_options(t(), 1, 24)`, `light_off_options=light_options(t(), values["light_off"])`, `light_on_options=light_options(t(), values["light_on"])`, and `preview` / `screen_size` for `door_preview` (move `preview_token` from `home.py` to `editing.py` as `Editor.preview_token()` and use it from both).

- [ ] **Step 1: Write the failing tests**

```python
def test_hour_options_cover_the_range_and_label_24_as_midnight():
    t = Translator("en-US")
    options = screen.hour_options(t, 1, 24)
    assert [v for v, _ in options] == [str(h) for h in range(1, 25)]
    assert options[7] == ("8", "8:00 AM") and options[-1] == ("24", "12:00 AM")
    assert screen.hour_options(Translator("pt-BR"), 0, 23)[8] == ("8", "8:00")


def test_light_options_are_every_half_hour():
    options = screen.light_options(Translator("pt-BR"), "22:00")
    assert len(options) == 48 and options[0] == ("00:00", "0:00") and options[45] == ("22:30", "22:30")


def test_light_options_keep_a_hand_set_time_off_the_grid():        # Review Focus 1
    values = [v for v, _ in screen.light_options(Translator("pt-BR"), "22:45")]
    assert len(values) == 49 and values[values.index("22:45") - 1] == "22:30"
    assert len(screen.light_options(Translator("pt-BR"), "not a time")) == 48
```

Import `screen` with `from inkdoor.web import screen`.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/test_web_pages.py -k "hour_options or light_options" -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement** both functions and the new template context.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/pytest tests/test_web_pages.py -k "hour_options or light_options" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inkdoor/web tests/test_web_pages.py
git commit -m "Screen: time options shared by the workday and the night light"
```

### Task 4: The Screen page

**Files:**
- Modify: `src/inkdoor/web/templates/screen.html`, `src/inkdoor/web/static/admin.css`, `src/inkdoor/web/static/admin.js`
- Modify: `src/inkdoor/locales/en-US.json`, `pt-BR.json`, `CHANGELOG.md`
- Test: `tests/test_web_pages.py`

**Interfaces:**
- Consumes: the Task 2 macros and the Task 3 context. Field names stay `screen`, `language`, `timezone`, `clock`, `workday_start`, `workday_end`, `workdays`, `min_gap_minutes`, `light_enabled`, `light_off`, `light_on`, `refresh_minutes`.
- `admin.js`: `input[data-enables]` disables the elements whose ids it lists while unchecked (on load and on change); `form[data-dirty]` gets the class `is-dirty` on its first `input` or `change` event. The save bar shows `admin.unsaved` only under `.is-dirty`.
- New keys: `admin.section_device`, `section_language`, `section_workday`, `section_workday_help`, `section_light`, `section_light_help`, `section_server`, `field_light_switch`, `unit_minutes`, `unsaved`, `preview_after_save`, `weekdays_short` (a list of seven). Changed text: `field_workday_start` "Starts at", `field_workday_end` "Ends at", `field_min_gap` "Shortest free gap", `field_refresh` "Read the calendars every" (units leave the labels), `clock_auto` "By language". Remove keys the template no longer uses.

- [ ] **Step 1: Write the failing tests**

```python
def test_screen_times_are_all_selects(logged):
    page = logged.get("/screen").get_data(as_text=True)
    for name in ("workday_start", "workday_end", "light_off", "light_on"):
        assert re.search(rf'<select[^>]*\bname="{name}"', page)
    assert 'type="time"' not in page
    assert page.count('name="workdays"') == 7 and 'name="port"' not in page


def test_screen_round_trips_a_workday_ending_at_24(logged, state):       # Review Focus 2
    save_screen(logged, workday_start="0", workday_end="24")
    assert read_raw(state.config_path).data["display"]["workday_end"] == 24
    assert re.search(r'<option value="24"\s+selected', logged.get("/screen").get_data(as_text=True))


def test_saving_keeps_a_light_time_off_the_grid(logged, state):          # Review Focus 1
    write_display(state, light_off="22:45", light_on="07:00")
    page = logged.get("/screen").get_data(as_text=True)
    assert re.search(r'<option value="22:45"\s+selected', page)
    save_screen(logged, light_enabled="1", light_off="22:45", light_on="07:00")
    assert read_raw(state.config_path).data["display"]["light_off"] == "22:45"
```

`save_screen(client, **overrides)` posts the page's current values plus the overrides with the CSRF token and digest; `write_display(state, **keys)` edits `[display]` in the test config. Reuse this file's existing helpers for both if it has them; otherwise add them beside the tests.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/test_web_pages.py -k "screen_times or ending_at_24 or off_the_grid" -v`
Expected: FAIL.

- [ ] **Step 3: Implement the template.** `<div class="split">` with the form column and `<aside class="side">` holding `door_preview` and `admin.preview_after_save`. Five `<section class="card">` in the spec's order: Device (model select as today); Language and time (language and time zone in a two-column row, `segmented` for `clock`); Workday (two `time_select`s joined by the existing shared help, `chips` for `workdays` with `weekdays_short`, `number_field` for `min_gap_minutes`); Night light (`switch("light_enabled", ..., enables="light_off light_on")` in the card header, two `time_select`s); Server (`number_field` for `refresh_minutes`, `readonly_row` for the port). The form carries `data-dirty`; the save bar is `<div class="save-bar">` with the marker and the Save button, `position: sticky; bottom: 0`. Keep every `aria-describedby` link and the `locked` language branch.

- [ ] **Step 4: Implement the two `admin.js` behaviors** and run `node --check src/inkdoor/web/static/admin.js`.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS (including `test_i18n.py` and `test_form_fields_reference_existing_help_and_errors`).

- [ ] **Step 6: Look at it** in both languages and themes at 1280 px and 375 px, and once with JavaScript off: the seven weekday chips fit one row at 375 px in pt-BR, the save bar stays reachable, and with JavaScript the light selects gray out when the switch is off.

- [ ] **Step 7: Changelog and commit.** Changelog: "Admin: the Screen page is grouped, and workday and night light times use the same control."

```bash
git add src/inkdoor tests/test_web_pages.py CHANGELOG.md
git commit -m "Screen: grouped cards, one time control, chips and a sticky save bar"
```

---

## Part 3: Calendars and Tasks (frkey/inkdoor#119)

### Task 5: Calendars list and the calendar form

**Files:**
- Modify: `src/inkdoor/web/templates/calendars.html`, `calendar_form.html`, `_test_result.html`
- Modify: `src/inkdoor/web/calendars.py` (`calendar_form_page` passes `name` and `digest` for the remove section)
- Modify: `src/inkdoor/web/static/admin.css`, both locale catalogs
- Test: `tests/test_web_pages.py`

**Interfaces:**
- Consumes: `icons.icon`, `m.action`, `m.test_form`, `m.switch`, the button classes.
- Routes unchanged: `POST /calendars/<i>/delete`, `/move`, `/test`.
- New keys: `admin.move_up_named` / `move_down_named` ("Move {name} up" / "Move {name} down", used as `aria-label`), `admin.busy_fact` ("Makes the door say “{word}”"), `admin.listed_fact` ("Listed only"), `admin.remove_calendar_title`, `admin.remove_calendar_help`. `admin.test` becomes "Test".
- `m.action` gains `aria_label=None` and `disabled=False`, and renders the label through `caller()` when called with `{% call %}` (for icon buttons).

- [ ] **Step 1: Write the failing tests**

```python
def test_calendar_rows_have_no_remove_and_keep_both_arrows(logged):
    page = logged.get("/calendars").get_data(as_text=True)
    assert "/delete" not in page
    assert page.count('name="direction" value="up"') == 3
    assert page.count('name="direction" value="down"') == 3
    assert len(re.findall(r"<button[^>]*\bdisabled", page)) == 2      # first up, last down


def test_remove_lives_on_the_edit_page(logged, state):
    page = logged.get("/calendars/1").get_data(as_text=True)
    assert 'action="/calendars/1/delete"' in page and "data-confirm=" in page
    assert 'action="/calendars/new/delete"' not in logged.get("/calendars/new").get_data(as_text=True)


def test_only_add_calendar_is_a_primary_button_on_the_list(logged):
    page = logged.get("/calendars").get_data(as_text=True)
    assert len(re.findall(r'class="button"', page)) == 1
```

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/test_web_pages.py -k "no_remove or edit_page or primary_button" -v`
Expected: FAIL.

- [ ] **Step 3: Implement.** `calendars.html`: one `<ol class="card rows">`; each `<li class="row">` has the marker (28 px), the name as `<h2>`, one facts line (`busy_fact` with `card.status_label or default_label`, or `listed_fact`; then the masked link in `.mask`), and `.row-actions`: `test_form`, Edit (`button-secondary`), then up and down icon buttons, both always rendered, `disabled` on the first row's up and the last row's down. The test slot sits inside the row under the facts. `calendar_form.html`: the same fields in a `.split` with the "Where do I find the link?" `howto` in the side column (open on a new calendar); "Marks you as busy" as `m.switch("busy", ...)`; on edit, a last `<section class="card danger-zone">` with the title, help and the `m.action(... "button-danger", confirm=...)` form. Update `test_move_up_down_and_delete` and `test_calendars_page_lists_markers_and_masks` only where they assert the old markup.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inkdoor tests/test_web_pages.py
git commit -m "Calendars: one list with icon move buttons; remove moves to the edit page"
```

### Task 6: Tasks page

**Files:**
- Modify: `src/inkdoor/web/templates/tasks.html`, `src/inkdoor/web/static/admin.css`, both locale catalogs, `CHANGELOG.md`
- Regenerate: `docs/img/admin-calendars-*.png` (`scripts/docs_images.py`)
- Test: `tests/test_web_pages.py`

**Interfaces:**
- Consumes: `m.number_field`, `m.link_field`, `m.test_form`, `m.action`. Routes and field names (`url`, `name`, `overdue_days`) unchanged.
- New keys: `admin.unit_days`, `admin.remove_tasks_title`, `admin.remove_tasks_help`. `field_overdue_days` loses its unit.

- [ ] **Step 1: Write the failing test**

```python
def test_tasks_page_shows_the_link_once_in_one_card(logged):
    page = logged.get("/tasks").get_data(as_text=True)
    assert page.count("tasks.example") == 1          # the mask, as the link field's placeholder
    assert page.count('class="card') == 2            # the form card and the remove section
    assert 'action="/tasks/delete"' in page
```

Use the masked host of this file's tasks fixture in place of `tasks.example`.

- [ ] **Step 2: Run and see it fail**

Run: `.venv/bin/pytest tests/test_web_pages.py -k "link_once" -v`
Expected: FAIL (the mask appears twice today).

- [ ] **Step 3: Implement.** One form card: a header row with the list's name and `test_form` when a link is set, the test slot under it, then `link_field`, the TickTick `howto`, `name`, and `number_field("overdue_days", ..., t("admin.unit_days"))`, then Save. When a list exists, a `danger-zone` card with the remove action. No list yet: the same form card with the `howto` open and no remove section (one card).

- [ ] **Step 4: Run the whole suite, regenerate the Calendars screenshots, look at both pages** in both languages and themes at 1280 px and 375 px.

Run: `.venv/bin/pytest`
Expected: PASS.

- [ ] **Step 5: Changelog and commit.** Changelog: "Admin: Calendars and Tasks are simpler lists; removing a calendar now happens on its edit page."

```bash
git add src/inkdoor tests/test_web_pages.py CHANGELOG.md docs/img
git commit -m "Tasks: one form card with the link shown once"
```

---

## Part 4: Home dashboard (frkey/inkdoor#120)

### Task 7: Per-source health in the snapshot

**Files:**
- Modify: `src/inkdoor/sources.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Produces, in `sources.py`:

```python
@dataclass
class SourceHealth:
    kind: str                     # "calendar" | "tasks"
    name: str
    style: str | None             # the calendar's marker; None for tasks
    busy: bool
    state: str                    # "ok" | "stale" | "failed" | "unset"
    items: int                    # events today (calendar) or tasks shown; 0 when failed or unset
    read_at: dt.datetime | None   # when the data in use was read; None when failed or unset
    reason: str | None            # failure category when stale or failed, else None

def failure_reason(ex: Exception) -> str: ...
```

- `failure_reason` returns one of `"timeout"`, `"denied"`, `"not_found"`, `"http"`, `"unreachable"`, `"other"`: `net.FetchError` with `reason == "timeout"` and `isolate.CalendarTimeout` give `"timeout"`; `FetchError` with `reason == "http"` gives `"denied"` for status 401 or 403, `"not_found"` for 404, else `"http"`; any other `FetchError` gives `"unreachable"`; everything else `"other"`. (The spec's "not a calendar" case folds into `"other"`.)
- `Snapshot` gains `health: list = field(default_factory=list)`, in config order, calendars then tasks, including sources without a link (`"unset"`).
- `SourceCache.put(key, day, items, at: dt.datetime | None = None)` stores `at`; new `SourceCache.read_at(key, day) -> dt.datetime | None`. `collect` passes `at=now`.
- `Snapshot.errors` and `Snapshot.unknown` are unchanged.

- [ ] **Step 1: Write the failing tests** (reuse this file's `cfg` fixture and its way of making a fetch fail)

```python
def test_health_of_a_good_read(cfg):
    snap = collect(cfg, now=NOW, cache=SourceCache())
    first = snap.health[0]
    assert (first.kind, first.state, first.read_at, first.reason) == ("calendar", "ok", NOW, None)
    assert first.items == len([e for e in snap.today if e.source == first.name])


def test_a_failed_read_with_todays_cache_is_stale(cfg, monkeypatch):     # Review Focus 3
    cache = SourceCache()
    collect(cfg, now=NOW, cache=cache)
    break_fetch(monkeypatch, net.FetchError("timeout"))
    health = collect(cfg, now=NOW + dt.timedelta(minutes=5), cache=cache).health[0]
    assert (health.state, health.read_at, health.reason) == ("stale", NOW, "timeout")


def test_a_failed_read_without_cache_is_failed(cfg, monkeypatch):        # Review Focus 3
    break_fetch(monkeypatch, net.FetchError("http", status=403))
    snap = collect(cfg, now=NOW, cache=SourceCache())
    assert (snap.health[0].state, snap.health[0].reason, snap.health[0].read_at) == ("failed", "denied", None)
    assert snap.health[0].name in snap.unknown


def test_a_source_without_a_link_is_unset(cfg):
    cfg["calendar"][0]["url"] = ""
    assert collect(cfg, now=NOW, cache=SourceCache()).health[0].state == "unset"


def test_health_never_holds_a_link_or_exception_text(cfg, monkeypatch):
    break_fetch(monkeypatch, RuntimeError("https://secret.example/token"))
    health = collect(cfg, now=NOW, cache=SourceCache()).health
    assert "secret.example" not in repr(health) and health[0].reason == "other"
```

`break_fetch` and `NOW` stand for this file's existing helpers; build `FetchError` the way `net.py` defines it.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/test_sources.py -k "health or stale or unset" -v`
Expected: FAIL.

- [ ] **Step 3: Implement** in `collect`: build one `SourceHealth` per calendar and for the task list in the same loop that fills `errors`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inkdoor/sources.py tests/test_sources.py
git commit -m "Sources: record each source's health in the snapshot"
```

### Task 8: Timeline, next status and the last image fetch

**Files:**
- Create: `src/inkdoor/dashboard.py`
- Modify: `src/inkdoor/state.py`, `src/inkdoor/server.py:55-68` (`_render_snapshot`), `src/inkdoor/web/__init__.py:392-420` (`kindle`)
- Test: `tests/test_dashboard.py` (new), `tests/test_server.py`, `tests/test_web_core.py`

**Interfaces:**
- Produces, in `dashboard.py`:

```python
@dataclass
class Block:
    start: dt.datetime
    end: dt.datetime
    style: str
    busy: bool

@dataclass
class Timeline:
    start: dt.datetime            # the workday's start today
    end: dt.datetime              # the workday's end today
    blocks: list[Block]

def build_timeline(snap: Snapshot, cfg: dict) -> Timeline | None: ...
def next_word(snap: Snapshot, cfg: dict, t: Translator, when: dt.datetime | None) -> str | None: ...
```

- `build_timeline` returns `None` when `snap.configured != "busy"` or today is not in `display.workdays`. Blocks come from `snap.today`, skip all-day events, are clipped to `[start, end]`, dropped when empty after clipping, and sorted by start. `end` for `workday_end = 24` is the next midnight.
- `next_word` returns `compute_status(dataclasses.replace(snap, now=when), cfg, t).word`, or `None` when `when` is `None` or `snap.configured == "nothing"`.
- `RenderInfo` gains `sources: list = field(default_factory=list)`, `timeline: Timeline | None = None`, `next_word: str | None = None`. `_render_snapshot` fills them from `snap.health`, `build_timeline` and `next_word(snap, cfg, t, change)`.
- `ServerState` gains `last_fetch_at: float | None = None` (wall time). The `kindle` route sets it to `clock()` when it answers with an image (not the 503) and `"t" not in request.args`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dashboard.py
def test_blocks_are_clipped_to_the_workday_and_all_day_is_left_out():      # Review Focus 4
    snap = snapshot(events=[event("07:00", "09:00"), event("18:30", "20:00", style="striped"),
                            event("10:00", "11:00", busy=False), all_day_event()])
    tl = build_timeline(snap, cfg(workday_start=8, workday_end=19))
    assert [(b.start.hour, b.start.minute, b.end.hour, b.end.minute) for b in tl.blocks] == \
        [(8, 0, 9, 0), (10, 0, 11, 0), (18, 30, 19, 0)]
    assert [b.style for b in tl.blocks] == ["solid", "solid", "striped"]
    assert [b.busy for b in tl.blocks] == [True, False, True]


def test_an_event_wholly_outside_the_workday_is_dropped():
    assert build_timeline(snapshot(events=[event("05:00", "06:00")]), cfg()).blocks == []


def test_no_timeline_on_a_day_off_or_without_a_busy_calendar():
    assert build_timeline(snapshot(weekday=6), cfg(workdays=[0, 1, 2, 3, 4])) is None
    assert build_timeline(snapshot(configured="no_busy"), cfg()) is None


def test_next_word_is_the_status_at_the_next_change():
    snap = snapshot(now="10:20", events=[event("10:00", "11:00")])
    t = Translator("en-US")
    assert next_word(snap, cfg(), t, at("11:00")) == t("status.free")
    assert next_word(snap, cfg(), t, None) is None
```

`snapshot`, `event`, `all_day_event`, `cfg` and `at` are small builders to write at the top of the new file (a `Snapshot` on a fixed Thursday in `America/Sao_Paulo`, `Event`s of the "Work" calendar). Use the catalog's real key for the free status word in place of `status.free`.

```python
# tests/test_web_core.py
def test_kindle_fetch_is_recorded_but_the_admin_preview_is_not(app, state, rendered, clock):
    c = client(app)
    get(c, "/kindle.png?t=123")
    assert state.last_fetch_at is None
    get(c, "/kindle.png")
    assert state.last_fetch_at == clock()


def test_a_503_is_not_a_fetch(app, state):
    get(client(app), "/kindle.png")
    assert state.last_fetch_at is None
```

```python
# tests/test_server.py
def test_render_info_carries_sources_timeline_and_next_word(...):
    # run one cycle with this file's existing fixture config, then:
    info = state.last_render
    assert [s.name for s in info.sources] == [c["name"] for c in state.cfg["calendar"]] + ["TickTick"]
    assert info.timeline is None or info.timeline.start < info.timeline.end
    assert info.next_word is None or isinstance(info.next_word, str)
```

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/test_dashboard.py tests/test_web_core.py tests/test_server.py -k "timeline or next_word or blocks or outside or fetch or carries" -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `dashboard.py`, the `RenderInfo` and `ServerState` fields, `_render_snapshot` and the `kindle` route.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/inkdoor tests
git commit -m "Server: timeline, next status and last image fetch for the admin Home"
```

### Task 9: The Home page

**Files:**
- Modify: `src/inkdoor/web/templates/home.html`, `src/inkdoor/web/home.py`, `src/inkdoor/web/static/admin.css`, `src/inkdoor/web/static/admin.js`
- Modify: both locale catalogs, `CHANGELOG.md`, `README.md` and `README.pt-BR.md` (the Home screenshot's alt text)
- Regenerate: `docs/img/admin-home-*.png`
- Test: `tests/test_web_core.py`, `tests/web_helpers.py`

**Interfaces:**
- Consumes: `RenderInfo.sources`, `.timeline`, `.next_word`, `.next_change`; `ServerState.last_fetch_at`, `.next_render_at`; `m.door_preview`, `m.source_state`, `icons.icon`.
- `home.py` builds view data, so the template holds no arithmetic:
  - `source_rows(last) -> list[dict]` with `name`, `style`, `kind`, `state`, `state_text`, `sentence`.
  - `timeline_view(timeline, now) -> dict | None` with `width` (1000), `blocks` (each `x`, `w`, `style`, `busy`, integers in the 0 to 1000 range), `now_x` (or `None` outside the workday), `ticks` (label and `x` for the start, the end and every second hour between), and `summary` (the text alternative: the busy periods as "9:00–9:30, 10:00–11:00", or the "no meetings" text).
  - `facts` for the status block: next change (time, plus `next_word` when known), drawn at / next draw, last fetch as a duration ago ("2 min ago", through `Translator.duration`) or the "not fetched yet" text.
- Sentences per state: `ok` "Read at {time} · {n} events today" (plural form through `n=`; tasks use their own key); `stale` "No answer since then · using the data from {time}" plus the reason text; `failed` the reason text plus "no data today"; `unset` "No link yet".
- Reason texts, new keys `admin.reason_timeout`, `reason_denied`, `reason_not_found`, `reason_http`, `reason_unreachable`, `reason_other`, worded after the matching `check.*` messages. Other new keys: `admin.status_now`, `next_change`, `next_change_to`, `drawn_at`, `last_fetch`, `last_fetch_never`, `today_title`, `timeline_alt`, `timeline_none`, `now_marker`, `sources_title`, `manage_calendars`, `state_ok`, `state_stale`, `state_failed`, `state_unset`, `source_ok` (plural), `tasks_ok` (plural), `source_stale`, `source_failed`, `source_unset`, `install_title`, `install_help`, `adjust_screen`. `admin.failing_sources` goes away.
- The timeline is one `<svg class="timeline" viewBox="0 0 1000 56" role="img" aria-label="{{ summary }}">`: a `<rect>` per block with `x`, `width` and `class="tl-solid|tl-striped|tl-outline"` (the striped fill is a `<pattern>` defined in the same `<svg>`), and a `<line class="tl-now">`. Colors come from CSS classes, never attributes that the CSP would treat as style.
- `admin.js`: in `pollPreview`, when `data.at` changes call `window.location.reload()`; delete `show`, `setStatus` and `showErrors`. `/status.json` keeps its five fields.

- [ ] **Step 1: Write the failing tests**

```python
def test_home_shows_status_facts_sources_and_timeline(app, state, rendered):
    state.last_render = info(sources=[health("Work", "ok", items=3), health("Company", "stale", reason="timeout")],
                             timeline=timeline(blocks=[("10:00", "11:00", "solid")]), next_word="Free")
    state.last_fetch_at = clock() - 120
    page = get(logged_in(app), "/").get_data(as_text=True)
    assert 'class="timeline"' in page and page.count("<rect") >= 1
    assert "state-ok" in page and "state-stale" in page
    assert "Free" in page and "FetchError" not in page and "timeout" not in page


def test_a_stale_source_is_never_shown_as_up_to_date(app, state, rendered):     # Review Focus 3
    state.last_render = info(sources=[health("Company", "stale", reason="timeout")])
    page = get(logged_in(app), "/").get_data(as_text=True)
    assert "state-ok" not in page and Translator("en-US")("admin.state_stale") in page


def test_home_without_sources_or_timeline(app, state, rendered):                # Review Focus 5
    state.last_render = info(sources=[], timeline=None)
    page = get(logged_in(app), "/").get_data(as_text=True)
    assert 'class="timeline"' not in page and 'class="card sources"' not in page


def test_source_names_are_escaped_on_home(app, state, rendered):                # Review Focus 5
    state.last_render = info(sources=[health('<b>&"', "ok")])
    page = get(logged_in(app), "/").get_data(as_text=True)
    assert "<b>&" not in page and str(escape('<b>&"')) in page


def test_status_json_keeps_its_fields(app, state, rendered):
    data = get(logged_in(app), "/status.json").get_json()
    assert set(data) == {"at", "word", "headline", "updated", "errors"}


def test_timeline_view_places_blocks_in_a_1000_wide_box():
    view = home.timeline_view(timeline(start="08:00", end="18:00", blocks=[("09:00", "10:00", "solid")]),
                              at("13:00"))
    assert (view["blocks"][0]["x"], view["blocks"][0]["w"], view["now_x"]) == (100, 100, 500)
    assert home.timeline_view(timeline(start="08:00", end="18:00"), at("20:00"))["now_x"] is None
```

All of these go in `tests/test_web_core.py`, which has the `rendered` and `clock` fixtures (take `clock` as a test argument where it is used; import `home` with `from inkdoor.web import home`). `info`, `health`, `timeline` and `at` are builders to add to `tests/web_helpers.py` (a `RenderInfo` with the given fields over fixed defaults; a `SourceHealth`; a `dashboard.Timeline` on a fixed day). If `timeline_view` lives inside `register`, move it to module level so the last test can call it.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/test_web_core.py -k "home or stale_source or timeline_view or status_json" -v`
Expected: the new tests FAIL; `test_status_json_keeps_its_fields` passes and must keep passing.

- [ ] **Step 3: Implement `home.py`** (`source_rows`, `timeline_view`, the facts) and **`home.html`**: the config and first-setup banners as today; `<div class="split">` with `<section class="status-block">` (ink background: `admin.status_now`, the word in weight 900, the headline, the three facts, "Update now" and a link to `/screen`) and `door_preview` with the Kindle model and the night light times under it; the Today card when `timeline` is set; a second `.split` with `<section class="card sources">` when there are rows and the "Install on the Kindle" card (zip button, `copy_field`, the two `howto`s). Keep `aria-live="polite"` on the status block and the `data-preview`, `data-at` and `data-poll` attributes the polling reads.

- [ ] **Step 4: Simplify `admin.js`** and run `node --check src/inkdoor/web/static/admin.js`.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS. Update `test_home_shows_status_and_preview` only where it asserts the old markup.

- [ ] **Step 6: Look at it** with a fictional config whose links fail (the "Knock first" state) and with the fixture calendars served from another machine address (the busy state): both languages, both themes, 1280 px and 375 px, JavaScript on and off. With one failing busy calendar and no cache, Home must not show anything that reads as free.

- [ ] **Step 7: Screenshots, docs, changelog, commit.** Regenerate `docs/img/admin-home-*.png`; update the Home image's alt text in `README.md` and `README.pt-BR.md`. Changelog: "Admin: Home is now a dashboard: what the door says and when it changes next, today's timeline, each source's state in plain words, and when the image was last fetched."

```bash
git add src/inkdoor tests CHANGELOG.md README.md README.pt-BR.md docs/img
git commit -m "Home: a dashboard of the door, its day and its sources"
```
