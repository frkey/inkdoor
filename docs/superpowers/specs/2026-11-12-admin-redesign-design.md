# Admin redesign ("ink and paper"): design

Status: direction approved in conversation on 2026-11-12 (review of the running admin plus a
three-screen mockup: Home, Screen, Calendars). Pending written-spec review.

## Goal

The web admin works, but it reads as a set of unrelated forms: the same concept is entered in
different ways, every field has the same weight, and Home says little about the door. Make the
admin look and behave like one product that belongs to the door it configures, and make Home a
real dashboard, **without changing the frontend stack**.

Success means:

- One way to enter each kind of value (a time is always entered and shown the same way).
- Home answers at a glance: what the door says, when it changes next, whether every source is
  being read, and whether the Kindle is fetching the image.
- Routine, rare and destructive actions are visibly different.
- Every page still works without JavaScript, in both languages, in light and dark, on a phone.

## Constraints (unchanged)

- Flask + Jinja templates + one `admin.css` + one `admin.js`. No build step, no framework, no
  new runtime dependency, no CDN.
- The Content-Security-Policy stays as it is: no inline styles, no inline scripts. Anything that
  needs per-item geometry (the timeline) is an inline `<svg>` with geometry attributes.
- `admin.js` remains optional: every page works without it.
- Routes, form field names, the config file format and the Kindle side do not change. No
  `KINDLE_VERSION` bump.
- All visible text goes through the `Translator`; `en-US.json` and `pt-BR.json` change together;
  times, dates and durations use `Translator.time()`, `.date_short()` and `.duration()`.
- The admin never shows a calendar link, and Home shows no meeting titles beyond what the door
  image itself already shows.

## Problems found in the review

| Page | Problem |
|---|---|
| Screen | Workday hours are bare numbers (`8`, `19`); the night light uses time pickers (`22:00`). |
| Screen | Eleven fields in one ungrouped column; two-digit numbers in full-width inputs, with the unit hidden in the label. |
| Screen | The light checkbox is styled differently from the weekday chips; its times stay editable when it is off. |
| Screen | Weekdays wrap onto a second line; the network port looks like an editable field. |
| Home | A failing source shows a Python class name ("Work: FetchError"). |
| Home | One-time Kindle setup takes more room than the door's status; no next change, no view of the day, no per-source health. |
| Calendars | "Test link" is the filled primary button on every card; "Remove" sits beside "Move down"; move buttons shift position between cards. |
| Tasks | The link is shown twice; two cards of different widths. |
| All | Lists are 1040 px wide and forms 640 px, left-aligned; gray inputs on white cards look disabled; secondary buttons are about 34 px tall; "Log out" appears twice. |

## Visual language

The admin borrows the door's look: black ink on paper, the same Inter weights, and the three
calendar markers (solid, striped, outline) as the main graphic element.

- **Color tokens** (CSS custom properties, light and dark, replacing the current set):
  `--paper` (page), `--surface` (cards), `--ink` (text and primary actions), `--ink-contrast`
  (text on ink), `--muted`, `--border`, `--border-strong` (inputs and secondary buttons),
  `--accent` (links, focus ring, the "now" line; the current blue), and the existing
  `--ok` / `--warn` / `--fail` with their backgrounds. Light values start from the mockup
  (`#f4f3f0`, `#ffffff`, `#1d1d1b`, `#5f5e5a`, `#dcdad4`, `#8a8882`, `#1f4f8a`). In dark mode
  `--ink` and `--paper` swap roles, so the ink block on Home becomes a light block.
- **Primary action** is ink (black in light mode), not blue. One primary button per view.
- **Type**: Inter 500/600/700 as bundled, plus 800 for the page title and the status word if the
  subset has it (otherwise 700; do not add a font file just for this). Page title 32 px, section
  title 18 px, body 16 px, help 14 px. `tabular-nums` wherever times line up.
- **Controls**: inputs and selects sit on `--surface` with a `--border-strong` outline and are
  at least 44 px tall; so is every button and link styled as a button. Text meets 4.5:1.
- **Status** is never color alone: an icon and words ("Up to date", "Old data", "No data").
- **Icons** are inline SVG in a Jinja macro file (`_icons.html`), stroke `currentColor`.
- **Page width**: every page uses the same 1120 px container. Forms keep a readable column and
  use the freed side for the door preview instead of empty space.

## Shared shell (`base.html`)

- Brand: a small door glyph and "inkdoor".
- Navigation: the same five items and routes (Home, Calendars, Tasks, Screen, Account).
- **Door status chip** on the right, on every page, linking to Home: the status word and, when
  it fits, the headline (from `state.last_render`). Hidden before the first render.
- "Log out" stays in the top bar only; the Account page drops its duplicate card and keeps the
  shared-computer hint as a line under the password form.
- Phone (under 640 px): brand, chip and "Log out" on the first row; the navigation on the second
  row, scrolling sideways instead of wrapping or clipping.

## Components (`_macros.html`)

New or changed macros, used by every page so that the same value is always entered the same way:

| Macro | Renders | Notes |
|---|---|---|
| `time_select` | `<select>` of times, labels from `Translator.time()` | The only time control in the admin. |
| `number_field` | Short numeric input (about 8 characters wide) with the unit as text beside it | Units come out of the labels. |
| `segmented` | Radio group drawn as joined segments | CSS only: visually hidden input + styled sibling. |
| `chips` | Checkbox group drawn as toggle chips | Same technique; one row of seven weekdays (short names). |
| `switch` | Checkbox drawn as a switch | A real checkbox; `appearance: none`. |
| `source_state` | Icon + words for ok / old data / no data | Used on Home, Calendars and Tasks. |
| `readonly_row` | Label and value as text | For values the admin cannot change (the port). |
| `door_preview` | The current `/kindle.png` in a Kindle-shaped frame | Used on Home and Screen. |

Buttons have three levels: primary (ink, filled), secondary (outline, ink text) and danger
(outline, red text, only inside a "Remove" section). The old `button-quiet` gray variant goes
away.

## Screen page

Five cards in a form column, with the door preview fixed beside it on wide screens (below the
form on a phone):

1. **Device**: Kindle model.
2. **Language and time**: language and time zone side by side; clock as a `segmented` control
   ("By language", "12-hour", "24-hour").
3. **Workday**: "Starts at" / "Ends at" as two `time_select`s; weekday `chips`; "Shortest free
   gap" as a `number_field` in minutes.
4. **Night light**: a `switch` in the card header; "Turns off at" / "Turns on at" as two
   `time_select`s; the note about the Kindle scripts version.
5. **Server**: "Read the calendars every" as a `number_field` in minutes; the network port as a
   `readonly_row`.

**Time fields.** The config format does not change: `workday_start` / `workday_end` stay whole
hours (0 to 24) and `light_off` / `light_on` stay `"HH:MM"`.

- Workday start offers 00:00 to 23:00 and workday end 01:00 to 24:00, in whole hours. The form
  still posts the hour as a number, so `forms.screen_form` keeps its validation.
- The night light offers every 30 minutes. A time in the file that is off that grid (for
  example `22:45`, set by hand) is added to the list and stays selected, so a save never changes
  it silently.
- Labels follow the admin's language and clock setting through `Translator.time()`, so en-US
  shows "8:00 AM" and pt-BR "08:00". The end-of-day value shows as midnight in that format.

**Behavior.** With JavaScript, turning the night light switch off disables its two selects, and
the save bar shows an "unsaved changes" marker once a field changes. Without JavaScript the
selects stay enabled and the bar just holds the Save button (today's behavior). The save bar
sticks to the bottom of the window. The preview shows the door as it is now, with a line saying
changes show after saving; there is no live re-render.

## Calendars and Tasks pages

**Calendars** becomes one list card, one row per calendar, in door order:

- Marker (larger), name, one line of facts ("Makes the door say 'In a meeting'" or "Listed
  only", then the shortened link), the `source_state`, and the actions.
- Actions: "Test" and "Edit" as secondary buttons, then move up / move down as icon buttons with
  `aria-label`s. Both arrows are always present; the one that cannot apply is disabled, so the
  buttons never shift between rows.
- The test result and a failing source's explanation open inside the row, under the facts.
- "Add calendar" is the page's only primary button.
- **Remove moves to the edit page**, in a separate "Remove this calendar" section at the bottom,
  with the existing confirmation flow (JavaScript confirm, or the server's confirm page).

**Calendar form**: same fields, using the shared macros (marker choice as `chips`-style radios,
"Marks you as busy" as a `switch`), one column beside the "Where do I find the link?" help,
which is open on a new calendar and collapsed on edit.

**Tasks** keeps its own page and route, and becomes one form card: the task list's state and
"Test" at the top, then link, name and "days overdue" (`number_field`), with the link shown
once. "Remove the task list" moves to a section at the bottom. (The mockup drew tasks on the
Calendars page; the spec keeps the page to leave routes and navigation unchanged.)

## Home page

Top row: the status block and the door preview. Then the day's timeline. Then sources and the
Kindle setup.

1. **Status block** (ink background): "The door says now", the status word, the headline, and
   three facts: next change (time and what the door will say, when known), when the screen was
   drawn and when the next draw is due, and when the image was last fetched. Buttons: "Update
   now" and a link to Screen.
2. **Door preview**: `door_preview`, with the Kindle model and the night light schedule under it.
3. **Today**: a horizontal timeline of the workday with one block per event, drawn with its
   calendar's marker pattern, and a line at the current time. No titles. Shown on workdays when
   at least one busy calendar is configured; otherwise the card is left out.
4. **Sources**: one row per calendar and the task list: marker, name, a sentence, and the
   `source_state`. A link to Calendars.
5. **Install on the Kindle**: the zip download, the image address with "Copy", and the two
   how-tos, in a narrower card. On a first setup (nothing configured) the existing first-setup
   banner stays at the top of the page.

Config problems keep their banners and the restore offer, restyled.

### New data from the server

All of it lives in memory on `ServerState` / `RenderInfo`, is rebuilt on every render, and is
never written to disk.

- **Per-source health.** The render loop records, for each configured source, its kind, name,
  marker style, a state, the time of its last successful read, how many items it has today, and
  on failure a reason category. States:
  - `ok`: read in this render.
  - `stale`: the read failed and the door is using this source's last good data from today
    (`SourceCache`).
  - `failed`: the read failed and there is no data for today.
  - `unset`: no link yet.
- **Failure reasons in plain language.** The reason is a category, never the exception text and
  never a link: timed out, could not connect, the server refused or did not find the link
  (HTTP status), the answer is not a calendar, or other. The wording reuses the messages
  `inkdoor check` and the link test already have. `Snapshot.errors` ("Name: ErrorType") stays
  for the door image and the log; the admin stops showing it.
- **Timeline.** For today: the workday bounds and a list of blocks (start, end, marker style,
  busy), clipped to the workday. No titles or locations are stored for it.
- **Last image fetch.** The `/kindle.png` handler records the time of the last request that
  does not carry the admin preview's `t` parameter. The page labels it as the last time the
  image was fetched, not as "the Kindle", because the address is public on the network.
  Nothing about the requester is stored.
- **What the door says next.** `RenderInfo.next_change` already holds the time. The status
  after it is included when the renderer can tell it cheaply (free until the next meeting, or
  the next meeting's status word); otherwise Home shows the time alone.

`/status.json` keeps its current fields. When the polled `at` changes, `admin.js` reloads the
page instead of patching the DOM piece by piece, so the new sections need no client code.

### The rule that matters

Home must not say more than the door knows. A `stale` source is shown as old data, with the time
of the data in use; a `failed` busy calendar matches the door's "Knock first". Nothing on Home
may read as "free" when the door itself would not say it.

## Login, confirm and error pages

Restyled with the shared tokens and components only: a centered narrow card, the brand above it,
one primary button. No change in behavior.

## Accessibility and responsive rules

- Real form controls everywhere; the drawn chips, segments and switch are native inputs with a
  visible focus ring on the drawn part.
- Touch targets at least 44 px; text contrast at least 4.5:1 in both themes.
- The timeline `<svg>` has `role="img"` and a text alternative listing the busy periods.
- Under 640 px: one column; the preview goes below the content; rows of a list stack (marker and
  name, then facts, then state, then actions); the save bar keeps Save at full width.
- pt-BR strings are longer: every row and button must wrap rather than clip.

## Delivery

Four independent pieces, one issue and one pull request each, in this order. Each leaves the
admin consistent on its own.

| # | Piece | Main files |
|---|---|---|
| 1 | Tokens, shell, components; restyle of login, account, confirm and error | `admin.css`, `base.html`, `_macros.html`, `_icons.html`, `login.html`, `account.html`, `confirm.html`, `error.html` |
| 2 | Screen page | `screen.html`, `web/screen.py`, `web/forms.py`, `admin.js` |
| 3 | Calendars, calendar form and Tasks | `calendars.html`, `calendar_form.html`, `tasks.html`, `_test_result.html`, `web/calendars.py` |
| 4 | Home dashboard and its server data | `home.html`, `web/home.py`, `web/__init__.py`, `state.py`, `server.py`, `sources.py`, `admin.js` |

Each pull request also carries: both locale catalogs, a `CHANGELOG.md` line, and new admin
screenshots in `docs/img/` (light and dark, both languages) where the page it changes is shown
in the README or `docs/`.

## Testing

- `tests/test_web_pages.py`: each page renders in both languages; the Screen form round-trips
  every value, including a workday ending at 24 and a night light time off the 30-minute grid;
  the remove actions answer from their new place; no page contains a `style=` attribute or an
  inline script.
- `tests/test_server.py` / `tests/test_sources.py`: per-source health for a good read, a failed
  read with cached data (`stale`), a failed read without it (`failed`) and an unset link; the
  timeline clips to the workday; no link or exception text reaches the health record.
- `tests/test_web_core.py`: `/kindle.png` records a fetch without `t` and not one with it.
- `tests/test_i18n.py` already fails when the catalogs differ.
- By hand, for every piece: each page in en-US and pt-BR, light and dark, at 1280 px and 375 px,
  and once with JavaScript turned off.

## Out of scope

- A JavaScript framework, a CSS framework or a build step.
- Live preview of unsaved Screen settings (it would need a second render path).
- Drag-and-drop ordering of calendars.
- Merging Calendars and Tasks into one page, or renaming routes.
- History or charts of past statuses; anything stored on disk about fetches.
- Changes to the door image, the Kindle scripts or the config file format.
