---
name: caloogy-calendar
description: Read and write the user's Caloogy calendar (calendar.caloogy.com) with the caloogy-calendar CLI — add, list, change, tick off or delete events from plain language ("dentist tomorrow 3 to 4pm"), and sync events between Caloogy and Feishu / Lark (lark-cli or feishu-cli), Google Calendar or .ics files in either direction. Use when the user mentions their Caloogy calendar, calendar.caloogy.com, or asks to copy / sync calendar events into or out of Caloogy.
---

# caloogy-calendar

`caloogy-calendar` reads and writes the user's own calendar on calendar.caloogy.com. Every event lives on **one
day** in the user's **local wall-clock time**: `date` (YYYY-MM-DD), optional `start` / `end` (HH:MM, 24-hour; `24:00`
= midnight), `title`, optional `location`, `attendees`, `meeting_url`, and `done` (ticked off). No start = an
all-day / untimed item.

Always pass `--json` and read the JSON — the plain output is for people.

## First time

```bash
caloogy-calendar whoami --json          # exit code 3 = not logged in
caloogy-calendar login --no-wait --json # prints verify_url + user_code; show both to the user
caloogy-calendar login --device-code <device_code from above> --json   # waits until they press Allow (≤10 min)
```

The user must open `verify_url` themselves, check the code and press **Allow**. Never try to approve it for them. If
the tool isn't installed: `uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/calendar"`
(or the same with `pipx install`).

## From plain language

Work out the real date first (run `date` — never guess today's date or weekday), then:

| The user says | Run |
|---|---|
| "dentist tomorrow 3 to 4pm" | `caloogy-calendar add "Dentist" --date tomorrow --start 15:00 --end 16:00 --json` |
| "gym Friday at 7, an hour" | `caloogy-calendar add "Gym" --date 2026-10-30 --start 07:00 --duration 1h --json` |
| "call mom on Sunday" (no time) | `caloogy-calendar add "Call mom" --date 2026-11-01 --json` |
| "lunch with Ann at Noma, 12:30" | `add "Lunch with Ann" --date … --start 12:30 --location "Noma" --attendees "Ann"` |
| "what's on this week?" | `caloogy-calendar list --days 7 --json` |
| "move the dentist to 5pm" | `list` to find its `id`, then `update <id> --start 17:00 --end 18:00 --json` |
| "I did the gym" | `update <id> --done --json` |
| "cancel the dentist" | `list`, then `delete <id> --json` |

- Titles are short ("Dentist", "1:1 with Ann") — time, place and people go in their own flags.
- No end time given → leave `--end` out (the calendar shows 30 minutes); don't invent one.
- `add` won't make a duplicate: same day + same start + same title returns `"created": false`.
- An id (`2026-10-25-1a2b3c4d`) changes whenever the event changes — use the id returned by the last
  `add` / `update` / `list`, and `list` again if one says "No event with that id".
- An event can't cross midnight: add one piece per day (e.g. 22:00–24:00 and 00:00–02:00).
- Ask before deleting more than a couple of events, and before any bulk import into the calendar.

## Sync with Feishu / Lark

The same rule decides "already there" both ways: **same day, same start time, same title** (case-insensitive).
Re-running a sync never makes duplicates. A changed time or title counts as a new event (the old one stays — tell the
user, and offer to delete it).

### Feishu → Caloogy

```bash
# 1. dump the Feishu events (user identity; ranges over 40 days are split automatically)
lark-cli calendar +agenda --as user --start 2026-10-01 --end 2026-12-31 > /tmp/feishu.json
#    or: feishu-cli calendar list-events <calendar_id> --start-time "2026-10-01T00:00:00+08:00" --end-time "2026-12-31T23:59:59+08:00" -o json > /tmp/feishu.json
# 2. preview, then write
caloogy-calendar import /tmp/feishu.json --dry-run --json
caloogy-calendar import /tmp/feishu.json --json
```

`import` understands Feishu / Lark event JSON (`summary`, `start_time` / `end_time` with `timestamp` or `date`,
`location`, `attendees`, `vchat.meeting_url`, cancelled events are skipped), Google Calendar JSON, generic
`{title, start, end}` lists with ISO times, and `.ics` files. Times are converted to this computer's time zone
(`--tz Asia/Shanghai` to choose another). Feishu all-day events end on their last day (`--all-day-end inclusive`, the
JSON default); `.ics` / Google ones end the day after (`exclusive`, the .ics default). Recurring events in a raw
`.ics` are skipped — export instances instead. If the JSON shape isn't recognised (0 events), reshape it yourself
into `[{"title", "start": ISO, "end": ISO}]` and import that.

### Caloogy → Feishu

```bash
lark-cli calendar +agenda --as user --start 2026-10-01 --end 2026-12-31 > /tmp/feishu.json
caloogy-calendar export --from 2026-10-01 --to 2026-12-31 --not-in /tmp/feishu.json --json
```

`export` prints only the Caloogy events missing from Feishu, each with `start_iso` / `end_iso` (with the local
offset) and `all_day`. Create each one in Feishu, e.g.
`lark-cli calendar +create --as user --summary "<title>" --start "<start_iso>" --end "<end_iso>"`
(all-day items: create an all-day event on `date`, see `lark-cli calendar events create` /
`lark-cli schema calendar.events.create`). Ticked-off items are left out unless `--include-done`. Show the user the
list and confirm before creating many events.

### Other calendars

`caloogy-calendar export --format ics --from … --to … > caloogy.ics` gives a file Google / Apple / Outlook can import;
`caloogy-calendar import their.ics` goes the other way.

## Commands

```
login [--no-wait | --device-code C] [--no-browser] [--name N]   logout   whoami
list   [--date D | --from D --to D | --days N] [-q TEXT]
add    TITLE --date D [--start T] [--end T | --duration 1h30m] [--location L] [--attendees "A, B"] [--meeting-url U]
update ID [--title] [--date] [--start] [--end] [--duration] [--clear-time] [--done | --not-done] [--location] ...
delete ID [ID ...]
import FILE|- [--dry-run] [--from D] [--to D] [--skip-all-day] [--all-day-end inclusive|exclusive] [--tz Z]
export [--from D --to D | --days N] [--format json|ics] [--not-in FILE] [--include-done] [--tz Z]
install-skill [--claude | --codex | --dir PATH]
```

Dates: `YYYY-MM-DD`, `today`, `tomorrow`, `yesterday`, `+N` / `-N` days. Times: `HH:MM`, `9:30`, `2pm`, or an ISO
date-time (`2026-10-25T14:00+08:00`, converted to local time). Exit codes: 0 ok, 1 failed, 2 bad arguments,
3 not logged in / token revoked (run `login`).
