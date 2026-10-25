# caloogy-calendar

The command line for [calendar.caloogy.com](https://calendar.caloogy.com): add, list, change and delete events, and
copy events in and out of Feishu / Lark, Google Calendar or `.ics` files. Made to be driven by Claude Code, Codex and
other terminal AI tools — every command has `--json`. Python 3.9+, no dependencies.

## Install

```bash
uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/calendar"
# or
pipx install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/calendar"
```

## Log in

```bash
caloogy-calendar login
```

It prints a link and a code and opens your browser. Check that the page shows the same code, and choose **Allow**. The
token is saved in `~/.config/caloogy/calendar.json` (only you can read it). It can add, change and delete events —
nothing else in your account. See or revoke connected tools on calendar.caloogy.com under your avatar →
**Command-line access**; `caloogy-calendar logout` revokes this computer's token.

## Let your AI use it

```bash
caloogy-calendar install-skill          # writes the skill to ~/.claude/skills and ~/.codex/skills
```

Restart Claude Code / Codex, then talk normally:

- "Put *dinner with Sam* on my Caloogy calendar Friday 7 to 9pm."
- "What's on my calendar this week?"
- "Move tomorrow's dentist to 5pm." · "Tick off the gym."
- "Copy everything from my Feishu calendar for November into Caloogy." (uses `lark-cli` or `feishu-cli`)
- "Put the Caloogy events that aren't in Feishu yet into Feishu."

## Commands

```bash
caloogy-calendar add "Dentist" --date tomorrow --start 15:00 --end 16:00 --location "Main St"
caloogy-calendar add "Gym" --date 2026-10-30 --start 7am --duration 1h
caloogy-calendar add "Call mom" --date +2                      # no time = all-day item
caloogy-calendar list --days 7                                  # --json for scripts
caloogy-calendar update 2026-10-25-1a2b3c4d --start 17:00 --end 18:00
caloogy-calendar update 2026-10-25-1a2b3c4d --done
caloogy-calendar delete 2026-10-25-1a2b3c4d

lark-cli calendar +agenda --as user --start 2026-11-01 --end 2026-11-30 > feishu.json
caloogy-calendar import feishu.json --dry-run                  # then without --dry-run
caloogy-calendar export --from 2026-11-01 --to 2026-11-30 --not-in feishu.json --json
caloogy-calendar export --days 30 --format ics > caloogy.ics
```

How events work:

- One event = one day, in your local time. `start` / `end` are `HH:MM` (24-hour); no `start` = all-day item. Events
  that cross midnight are split per day on import; `add` asks you to add each day's piece.
- "The same event" means **same day, same start, same title**. `add` and `import` never create a second copy, so a
  sync can be re-run safely. A changed time or title is a new event.
- An event's id (`2026-10-25-1a2b3c4d`) changes whenever the event does — commands print the new one.
- `import` reads Feishu / Lark JSON (`lark-cli calendar +agenda`, `feishu-cli calendar list-events -o json`), Google
  Calendar JSON, plain `[{"title", "start", "end"}]` lists with ISO times, and `.ics`. Cancelled events are skipped;
  so are recurring events inside a raw `.ics` (export single instances instead).
- `export` gives ISO start/end times with your offset, ready for `lark-cli calendar +create`, or an `.ics` file.

Exit codes: 0 ok · 1 failed · 2 bad arguments · 3 not logged in.

## Development

```bash
cd caloogy-work/calendar
PYTHONPATH=src python3 -m unittest discover -s tests
CALOOGY_CALENDAR_URL=http://localhost:5098 PYTHONPATH=src python3 -m caloogy_calendar whoami   # against a dev server
```
