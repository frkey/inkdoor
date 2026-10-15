# inkdoor

**English** · [Português (Brasil)](README.pt-BR.md)

**An old Kindle on your office door that tells people whether they can come in.**

inkdoor merges several calendars (Outlook, Google, any ICS link) and your TickTick tasks into
one e-ink screen. People outside can see from across the room whether you are in a meeting
and until when. You see the whole day, the free gaps between events, and what is left to do.

![Three inkdoor screens: in a meeting, free, and after hours](docs/img/screens-en-US.png)

<sub>Screens rendered with fictional data (`inkdoor demo`). The display is also available in
Brazilian Portuguese.</sub>

## How it works

```
 Outlook ─┐
 Outlook ─┤   ICS links    ┌───────────────────┐   1072×1448 PNG   ┌────────┐
 Google  ─┼──────────────▶ │ inkdoor (computer)│ ────────────────▶ │ Kindle │
 TickTick ┘                └───────────────────┘   every 5 min     └────────┘
```

- **On your computer** (`src/inkdoor`): a Python program reads the calendars, lays out the
  day, and draws the screen as a 16-shade grayscale image served on your local network.
- **On the Kindle** (`kindle/`): two *scriptlets* turn off the Kindle interface and show that
  image, refreshing it every few minutes.

Nothing goes through third-party services: calendars are read on your computer and the image
stays on your network.

## What the screen shows

- **Door status**: `IN A MEETING until 11:00 AM` (black) or `FREE until 4:30 PM` (outlined).
  Back-to-back meetings count as one block, so "until" is when you are actually out.
- **Today**: events from every calendar, explicit free gaps (`free · 1h 30m`), a *now* marker,
  and the current event highlighted. Past events collapse into one line when space is tight.
- **Tasks**: due today and overdue, with priority and time.
- **After hours**, the list switches to tomorrow.
- Each calendar has its own marker (solid, striped, outline), since e-ink has no color.
- **It never guesses.** If a calendar link fails, the last good data from today is reused; with
  no data at all the door says `KNOCK FIRST` instead of `FREE`.

## Getting started

### 1. Computer

Requires Python 3.10+.

```sh
git clone https://github.com/frkey/inkdoor.git
cd inkdoor
pip install -e .

cp config.example.toml config.toml   # paste your calendar links here
inkdoor check                        # tests every link
inkdoor serve                        # renders and serves http://<computer-ip>:8000/kindle.png
```

Where to find each calendar link: [docs/calendar-sources.md](docs/calendar-sources.md).

> `config.toml` is git-ignored: anyone with those links can read your calendars.

### 2. Kindle

You need a jailbroken Kindle. Step by step: [docs/kindle.md](docs/kindle.md). In short:

1. Copy `kindle/inkdoor/` to the root of the Kindle and `kindle/documents/*.sh` to `documents/`.
2. Put your computer's IP in `inkdoor/config.sh`.
3. In the library, open **inkdoor - test connection**, then **inkdoor - start display**.

## Language

The screen and all messages are in **English (en-US)** by default. Brazilian Portuguese is
built in:

```toml
[display]
language = "pt-BR"
```

You can also pass `--lang pt-BR` to any command. Times follow each language's convention
(12-hour for en-US, 24-hour for pt-BR); override with `clock = "24h"` or `clock = "12h"`.

To add a language, copy `src/inkdoor/locales/en-US.json`, translate the values, and add demo
content to `src/inkdoor/demo.py`. The tests fail if a catalog is missing any key.

## Commands

| Command | What it does |
|---|---|
| `inkdoor serve` | Renders the screen every `refresh_minutes` and serves it on `port`. Reloads the config each cycle. |
| `inkdoor render` | Renders `output/kindle.png` once. |
| `inkdoor check` | Tests each link: reachability, number of events, and whether titles come through or only "Busy". |
| `inkdoor demo 10:20 16:50` | Renders previews with fictional data, no calendars needed. |

Global options: `--config path/config.toml`, `--output dir/`, `--lang en-US|pt-BR`.

## Configuration

Everything lives in `config.toml`; see the comments in [`config.example.toml`](config.example.toml):

- `[display]`: `language`, `timezone`, `clock`, `workday_start` / `workday_end`, `workdays`,
  `min_gap_minutes`
- `[server]`: `port`, `refresh_minutes`
- `[[calendar]]` (one per calendar): `name`, `style` (`solid`, `striped`, `outline`), `busy`
  (whether it changes the door status), `status_label` (the big word, e.g. `"Busy"` for personal
  events), `url`
- `[tasks]`: TickTick subscription link and `overdue_days`

## Development

```sh
pip install -e ".[dev]"
pytest
```

```
src/inkdoor/
  sources.py     reads calendars (ICS) and tasks: recurrence, time zones, de-duplication
  render.py      screen layout and drawing
  i18n.py        translation and time/date formatting
  locales/       en-US.json (reference) and pt-BR.json
  server.py      periodic rendering and HTTP server
  check.py       inkdoor check
  demo.py        fictional data for previews
  fonts/         Inter (SIL OFL 1.1)
kindle/          scriptlets and scripts that run on the Kindle
tests/           tests with fictional calendars
```

Built for the Kindle Paperwhite 10th generation (1072×1448). Other models should work by
changing `W` and `H` in `render.py`.

## License

[MIT](LICENSE). The Inter typeface is licensed under the [SIL Open Font License](src/inkdoor/fonts/OFL.txt).
