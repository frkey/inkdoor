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
- **en-US is the default and the reference locale.** Every key must exist in `en-US.json`.
- **pt-BR is a first-class option and must stay in sync.** Whenever you add or change a key in
  `en-US.json`, update `pt-BR.json` in the same change. `tests/test_i18n.py` fails if the
  catalogs have different keys.
- Write en-US text in US English: "canceled", "color", 12-hour clock with AM/PM, "Oct 14".
  Write pt-BR text in natural Brazilian Portuguese with the 24-hour clock ("14:30").
- Format times, dates and durations through `Translator.time()`, `.time_short()`,
  `.date_header()` and `.duration()`, never with ad-hoc f-strings.
- **User docs exist in both languages.** `README.md` (English) is mirrored by
  `README.pt-BR.md`, and each file in `docs/` has a translation in `docs/pt-BR/`. Update both
  in the same change. Developer-only docs (this file, code comments) are English only.
- Demo content in `src/inkdoor/demo.py` exists per language; add an entry for any new locale.

## Project overview

inkdoor turns a jailbroken Kindle into a door sign that shows whether you are in a meeting.

- `src/inkdoor/`: Python package that runs on a computer. It reads ICS calendars and a
  TickTick subscription (`sources.py`), draws a 1072×1448 grayscale PNG (`render.py`) and
  serves it over HTTP (`server.py`).
- `kindle/`: POSIX shell scripts that run on the Kindle and display the PNG.

## Commands

```sh
pip install -e ".[dev]"
pytest                                   # all tests
inkdoor -o output demo 10:20 16:50       # render previews with fictional data
inkdoor -o output --lang pt-BR demo 10:20
cd kindle && shellcheck inkdoor/*.sh documents/*.sh
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
- Kindle scripts must be POSIX `sh` (BusyBox), use LF line endings (`.gitattributes` enforces
  it), and pass ShellCheck with `kindle/.shellcheckrc`.
- Fonts in `src/inkdoor/fonts/` are a Latin subset of Inter (SIL OFL 1.1). If you need a glyph
  outside that subset, re-subset from the upstream font and keep `OFL.txt`.

## Privacy

This is a public repository.

- Never commit `config.toml`; it holds secret calendar links and is git-ignored.
- Never put real calendar URLs, names, email addresses or meeting titles in code, tests, docs or
  screenshots. Use the fictional data in `demo.py` and `tests/fixtures/`.
