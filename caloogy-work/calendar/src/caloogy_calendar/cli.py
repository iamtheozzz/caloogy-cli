"""caloogy-calendar — read and write your calendar.caloogy.com from the terminal (and from Claude Code / Codex).

    caloogy-calendar login                       # once: approve in the browser
    caloogy-calendar add "Dentist" --date 2026-10-25 --start 14:00 --end 15:00
    caloogy-calendar list --days 7 --json
    caloogy-calendar import feishu.json          # events from Feishu / Lark, Google, .ics ...
    caloogy-calendar export --from 2026-10-01 --to 2026-10-31 --json

Run `caloogy-calendar <command> --help` for each command.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__
from .convert import ConvertError, export_event, key_of, load_foreign, local_zone, parse_when, to_ics

DEFAULT_URL = "https://calendar.caloogy.com"
SKILL_NAME = "caloogy-calendar"


class Fail(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- config

def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "caloogy" / "calendar.json"


def read_config() -> dict:
    try:
        return json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}


def write_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, p)


def base_url(args) -> str:
    return (getattr(args, "url", None) or os.environ.get("CALOOGY_CALENDAR_URL") or read_config().get("url") or DEFAULT_URL).rstrip("/")


def token() -> str:
    t = os.environ.get("CALOOGY_CALENDAR_TOKEN") or read_config().get("token")
    if not t:
        raise Fail("Not logged in. Run: caloogy-calendar login", 3)
    return t


# ---------------------------------------------------------------- HTTP

def request(args, method: str, path: str, body=None, auth: bool = True) -> tuple[int, dict]:
    headers = {"User-Agent": f"caloogy-calendar/{__version__}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = f"Bearer {token()}"
    req = urllib.request.Request(base_url(args) + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except ValueError:
            data = {}
        if e.code == 401 and auth:
            raise Fail(data.get("message") or "Your login was revoked or expired. Run: caloogy-calendar login", 3)
        return e.code, data
    except urllib.error.URLError as e:
        raise Fail(f"Can't reach {base_url(args)}: {e.reason}")


def api(args, method: str, path: str, body=None, ok=(200, 201)) -> dict:
    status, data = request(args, method, path, body)
    if status not in ok:
        raise Fail(data.get("message") or data.get("error") or f"HTTP {status}")
    return data


# ---------------------------------------------------------------- output

def emit(args, data, text: str | None = None) -> None:
    if args.json or text is None:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif text:
        print(text)


def line_of(ev: dict) -> str:
    when = f"{ev['start']}-{ev['end']}" if ev.get("end") else (ev.get("start") or "all day")
    bits = [f"  {when:<12} {'[x] ' if ev.get('done') else ''}{ev['title']}"]
    if ev.get("location"):
        bits.append(f"@ {ev['location']}")
    if ev.get("meeting_url"):
        bits.append(ev["meeting_url"])
    return "  ".join(bits) + ("" if ev.get("busy") or not ev.get("id") else f"   ({ev['id']})")


def table(events: list[dict]) -> str:
    if not events:
        return "No events."
    out, last = [], None
    for ev in events:
        if ev["date"] != last:
            last = ev["date"]
            out.append(f"{last} {date.fromisoformat(last).strftime('%a')}")
        out.append(line_of(ev))
    return "\n".join(out)


# ---------------------------------------------------------------- dates & times from the command line

def day_arg(s: str) -> date:
    t = (s or "").strip().lower()
    today = date.today()
    if t in ("today", "今天"):
        return today
    if t in ("tomorrow", "明天"):
        return today + timedelta(days=1)
    if t in ("yesterday", "昨天"):
        return today - timedelta(days=1)
    if re.fullmatch(r"[+-]\d{1,4}", t):
        return today + timedelta(days=int(t))
    try:
        return date.fromisoformat(t)
    except ValueError:
        raise Fail(f"Not a date: {s!r} (use YYYY-MM-DD, today, tomorrow or +N)", 2)


def time_arg(s: str | None, tz, flag: str) -> tuple[str | None, date | None]:
    """HH:MM (24h, also 9:30 / 930 / 2pm) -> ("09:30", None); an ISO date-time -> ("HH:MM" local, its date)."""
    if s is None:
        return None, None
    t = s.strip().lower()
    if t == "":
        return "", None
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?", t)
    if m:
        h, mi = int(m[1]), int(m[2] or 0)
        if m[3] == "pm" and h < 12:
            h += 12
        if m[3] == "am" and h == 12:
            h = 0
        if h > 24 or mi > 59 or (h == 24 and mi):
            raise Fail(f"{flag}: not a time: {s!r}", 2)
        return f"{h:02d}:{mi:02d}", None
    when = parse_when(s, tz)
    if isinstance(when, datetime):
        local = when.astimezone(tz)
        return f"{local.hour:02d}:{local.minute:02d}", local.date()
    raise Fail(f"{flag}: not a time: {s!r} (use HH:MM, 24-hour)", 2)


def duration_arg(s: str) -> int:
    m = re.fullmatch(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?\s*", s.lower())
    if not m or not (m[1] or m[2]):
        if s.strip().isdigit():
            return int(s)
        raise Fail(f"--duration: use e.g. 30m, 1h, 1h30m", 2)
    return int(m[1] or 0) * 60 + int(m[2] or 0)


def add_minutes(hhmm: str, n: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = min(h * 60 + m + n, 24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


# ---------------------------------------------------------------- commands

def cmd_login(args) -> None:
    url = base_url(args)
    if args.device_code:
        device = {"device_code": args.device_code, "interval": 2, "expires_in": 600}
    else:
        name = args.name or f"caloogy-calendar on {socket.gethostname().split('.')[0] or platform.node()}"
        status, device = request(args, "POST", "/api/cli/start", {"name": name}, auth=False)
        if status != 200:
            raise Fail(device.get("message") or f"Couldn't start a login (HTTP {status}).")
        if args.no_wait:
            emit(args, {"verify_url": device["verify_url"], "user_code": device["user_code"],
                        "device_code": device["device_code"], "expires_in": device["expires_in"],
                        "next": f"caloogy-calendar login --device-code {device['device_code']}"},
                 f"Open this link, check the code and choose Allow:\n\n  {device['verify_url']}\n  code: {device['user_code']}\n\n"
                 f"Then run:\n  caloogy-calendar login --device-code {device['device_code']}")
            return
        print(f"Open this link in your browser, check the code and choose Allow:\n\n  {device['verify_url']}\n\n"
              f"  code: {device['user_code']}\n\nWaiting for approval (up to 10 minutes)...", file=sys.stderr, flush=True)
        if not args.no_browser:
            try:
                webbrowser.open(device["verify_url"])
            except Exception:
                pass
    deadline = time.time() + float(device.get("expires_in") or 600)
    while time.time() < deadline:
        status, r = request(args, "POST", "/api/cli/poll", {"device_code": device["device_code"]}, auth=False)
        st = r.get("status")
        if status == 200 and st == "ok":
            cfg = read_config()
            cfg.update({"token": r["token"], "url": url, "account": r.get("account") or {}})
            write_config(cfg)
            acct = r.get("account") or {}
            who = acct.get("email") or acct.get("name") or acct.get("id")
            emit(args, {"ok": True, "account": acct, "config": str(config_path())}, f"Logged in as {who}.")
            return
        if st == "denied":
            raise Fail("The login was denied in the browser.")
        if st == "expired":
            raise Fail("The login link expired. Run caloogy-calendar login again.")
        if status == 429:
            time.sleep(10)
        time.sleep(float(device.get("interval") or 2))
    raise Fail("Timed out waiting for approval. Run caloogy-calendar login again.")


def cmd_logout(args) -> None:
    cfg = read_config()
    if cfg.get("token"):
        try:
            request(args, "DELETE", "/api/cli/tokens/self")
        except Fail:
            pass
    cfg.pop("token", None)
    cfg.pop("account", None)
    write_config(cfg)
    emit(args, {"ok": True}, "Logged out (the token was revoked).")


def cmd_whoami(args) -> None:
    me = api(args, "GET", "/api/me")
    emit(args, {**me, "url": base_url(args)}, f"{me.get('email') or me.get('name') or me['id']} (id {me['id']}) on {base_url(args)}")


def range_of(args) -> tuple[date, date]:
    if getattr(args, "date", None):
        d = day_arg(args.date)
        return d, d
    start = day_arg(args.from_) if args.from_ else date.today()
    if args.to:
        end = day_arg(args.to)
    else:
        end = start + timedelta(days=max(1, args.days) - 1)
    if end < start:
        raise Fail("--to is before --from", 2)
    return start, end


def fetch(args, start: date, end: date, base: str = "/api/events") -> list[dict]:
    out: list[dict] = []
    cur = start
    while cur <= end:                                     # the server answers up to 400 days at a time
        stop = min(end, cur + timedelta(days=399))
        out += api(args, "GET", f"{base}?from={cur.isoformat()}&to={stop.isoformat()}")["events"]
        cur = stop + timedelta(days=1)
    return out


def get_friends(args) -> list[dict]:
    return api(args, "GET", "/api/friends")["friends"]


def find_friend(args, who: str) -> dict:
    """a friend by 8-character id, or by name (exact, then unique start / substring, case-insensitive)"""
    friends = get_friends(args)
    w = who.strip().casefold()
    for test in (lambda f: f["id"] == w, lambda f: f["name"].casefold() == w,
                 lambda f: f["name"].casefold().startswith(w), lambda f: w in f["name"].casefold()):
        hits = [f for f in friends if test(f)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise Fail(f"{who!r} matches several friends: " + ", ".join(f"{f['name']} ({f['id']})" for f in hits) + " — use the id", 2)
    raise Fail(f"No friend called {who!r}. Run: caloogy-calendar friends", 2)


def shares_busy_only(friend: dict) -> bool:
    return bool(friend.get("busy_only"))


def cmd_friends(args) -> None:
    friends = get_friends(args)
    emit(args, {"friends": [{"id": f["id"], "name": f["name"], "busy_only": shares_busy_only(f)} for f in friends]},
         "\n".join(f"  {f['name']}  ({f['id']})" + ("  — busy times only" if shares_busy_only(f) else "") for f in friends) if friends
         else "No friends yet — add them in Caloogy Work (work.caloogy.com).")


def cmd_list(args) -> None:
    start, end = range_of(args)
    if args.friend:
        friend = find_friend(args, args.friend)
        events = fetch(args, start, end, f"/api/friends/{friend['id']}/events")
        if args.query:
            q = args.query.casefold()
            events = [e for e in events if q in e["title"].casefold() or q in (e.get("location") or "").casefold()]
        emit(args, {"friend": {"id": friend["id"], "name": friend["name"], "busy_only": shares_busy_only(friend)}, "from": start.isoformat(), "to": end.isoformat(),
                    "events": events},
             f"{friend['name']}'s calendar (read-only"
             + ("; they share only when they're busy" if shares_busy_only(friend) else "") + ")\n" + table(events))
        return
    events = fetch(args, start, end)
    if args.query:
        q = args.query.casefold()
        events = [e for e in events if q in e["title"].casefold() or q in (e.get("location") or "").casefold()]
    emit(args, {"from": start.isoformat(), "to": end.isoformat(), "events": events}, table(events))


def event_body(args, tz, partial: bool) -> dict:
    b: dict = {}
    start, start_day = time_arg(args.start, tz, "--start")
    end, end_day = time_arg(args.end, tz, "--end")
    if args.date:
        b["date"] = day_arg(args.date).isoformat()
    elif start_day:
        b["date"] = start_day.isoformat()
    elif not partial:
        raise Fail("--date is required (YYYY-MM-DD, today, tomorrow or +N)", 2)
    if start_day and end_day and end_day != start_day:
        if end_day == start_day + timedelta(days=1) and end == "00:00":
            end = "24:00"
        else:
            raise Fail("An event can't cross midnight here — add one piece per day.", 2)
    if getattr(args, "clear_time", False):
        b["start"], b["end"] = None, None
    if start is not None:
        b["start"] = start or None
    if end is not None:
        b["end"] = end or None
    if getattr(args, "duration", None):
        s = b.get("start")
        if not s:
            raise Fail("--duration needs --start", 2)
        b["end"] = add_minutes(s, duration_arg(args.duration))
    if args.title is not None:
        b["title"] = args.title
    if args.location is not None:
        b["location"] = args.location
    if args.attendees is not None:
        b["attendees"] = [a.strip() for a in re.split(r"[,，;；]", args.attendees) if a.strip()]
    if args.meeting_url is not None:
        b["meeting_url"] = args.meeting_url
    if getattr(args, "done", None) is not None:
        b["done"] = args.done
    return b


def cmd_add(args) -> None:
    tz = local_zone(args.tz)
    body = event_body(args, tz, partial=False)
    status, r = request(args, "POST", "/api/events", body)
    if status not in (200, 201):
        raise Fail(r.get("message") or f"HTTP {status}")
    ev = r["event"]
    emit(args, r, ("Added:\n" if r.get("created") else "Already there (same day, start and title):\n") + line_of(ev))


def cmd_update(args) -> None:
    tz = local_zone(args.tz)
    body = event_body(args, tz, partial=True)
    if not body:
        raise Fail("Nothing to change — pass --title, --date, --start, --end, --done ...", 2)
    r = api(args, "PATCH", f"/api/events/{args.id}", body)
    emit(args, r, "Updated:\n" + line_of(r["event"]) + "\n(the id changed with it)")


def cmd_delete(args) -> None:
    gone = []
    for eid in args.ids:
        api(args, "DELETE", f"/api/events/{eid}")
        gone.append(eid)
    emit(args, {"deleted": gone}, f"Deleted {len(gone)} event(s).")


def read_input(src: str) -> str:
    if src == "-":
        return sys.stdin.read()
    try:
        return Path(src).expanduser().read_text(encoding="utf-8-sig")
    except OSError as e:
        raise Fail(f"Can't read {src}: {e.strerror}", 2)


def cmd_import(args) -> None:
    tz = local_zone(args.tz)
    try:
        pieces, info = load_foreign(read_input(args.file), tz, args.all_day_end)
    except ConvertError as e:
        raise Fail(str(e), 2)
    if args.skip_all_day:
        pieces = [p for p in pieces if p.get("start")]
    if args.from_ or args.to:
        lo = day_arg(args.from_).isoformat() if args.from_ else "0000"
        hi = day_arg(args.to).isoformat() if args.to else "9999"
        pieces = [p for p in pieces if lo <= p["date"] <= hi]
    if args.dry_run:
        have: set = set()
        if pieces:
            days = sorted(p["date"] for p in pieces)
            have = {key_of(e) for e in fetch(args, date.fromisoformat(days[0]), date.fromisoformat(days[-1]))}
        plan = [{"status": "exists" if key_of(p) in have else "would-create", "event": p} for p in pieces]
        n = sum(x["status"] == "would-create" for x in plan)
        emit(args, {"dry_run": True, **info, "results": plan},
             "\n".join(f"  {x['status']:<12} {x['event']['date']} {x['event'].get('start') or 'all day':<6} {x['event']['title']}" for x in plan)
             + f"\n{n} to create, {len(plan) - n} already there (dry run — nothing written)."
             + (f"\nSkipped {info['skipped_recurring']} recurring event(s) — export them as single instances." if info["skipped_recurring"] else ""))
        return
    results: list[dict] = []
    for i in range(0, len(pieces), 400):
        results += api(args, "POST", "/api/events/batch", {"events": pieces[i:i + 400]})["results"]
    count = {k: sum(r["status"] == k for r in results) for k in ("created", "exists", "error")}
    errors = [f"  error: {pieces[i]['date']} {pieces[i]['title']}: {r['error']}" for i, r in enumerate(results) if r["status"] == "error"]
    emit(args, {**info, **count, "results": results},
         f"Created {count['created']}, already there {count['exists']}, failed {count['error']}."
         + ("\n" + "\n".join(errors) if errors else "")
         + (f"\nSkipped {info['skipped_recurring']} recurring event(s) — export them as single instances." if info["skipped_recurring"] else ""))
    if count["error"]:
        sys.exit(1)


def cmd_export(args) -> None:
    tz = local_zone(args.tz)
    start, end = range_of(args)
    events = fetch(args, start, end)
    if not args.include_done:
        events = [e for e in events if not e.get("done")]
    if args.not_in:
        try:
            theirs, _ = load_foreign(read_input(args.not_in), tz, args.all_day_end)
        except ConvertError as e:
            raise Fail(f"--not-in: {e}", 2)
        have = {key_of(p) for p in theirs}
        events = [e for e in events if key_of(e) not in have]
    if args.format == "ics":
        sys.stdout.write(to_ics(events, tz))
        return
    out = [export_event(e, tz) for e in events]
    emit(args, {"from": start.isoformat(), "to": end.isoformat(), "timezone": str(tz), "events": out}, None)


def skill_text() -> str:
    return (Path(__file__).with_name("SKILL.md")).read_text(encoding="utf-8")


def cmd_install_skill(args) -> None:
    home = Path.home()
    targets: list[Path] = []
    if args.dir:
        targets.append(Path(args.dir).expanduser())
    else:
        if args.claude or not args.codex:
            targets.append(home / ".claude" / "skills")
        if args.codex or not args.claude:
            targets.append(Path(os.environ.get("CODEX_HOME") or home / ".codex") / "skills")
    written = []
    for t in targets:
        d = t / SKILL_NAME
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(skill_text(), encoding="utf-8")
        written.append(str(d / "SKILL.md"))
    emit(args, {"written": written}, "Installed the skill for your AI tools:\n" + "\n".join(f"  {w}" for w in written)
         + "\nRestart Claude Code / Codex so they pick it up.")


# ---------------------------------------------------------------- argument parsing

def build_parser() -> argparse.ArgumentParser:
    # --json / --url work before or after the command; SUPPRESS keeps a subcommand from resetting what came before it
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output (for scripts and AI tools)")
    common.add_argument("--url", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(prog="caloogy-calendar", description="Read and write your calendar.caloogy.com.",
                                epilog="Times are 24-hour local wall-clock time (HH:MM). An event lives on one day.")
    p.add_argument("--json", action="store_true", help="machine-readable output (for scripts and AI tools)")
    p.add_argument("--url", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"caloogy-calendar {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    s = sub.add_parser("login", parents=[common], help="connect this computer to your account (approve in the browser)")
    s.add_argument("--name", help="how this tool shows up under Command-line access")
    s.add_argument("--no-browser", action="store_true", help="just print the link")
    s.add_argument("--no-wait", action="store_true", help="print the link and a device code, then exit (finish with --device-code)")
    s.add_argument("--device-code", help="finish a login started with --no-wait")
    s.set_defaults(fn=cmd_login)

    s = sub.add_parser("logout", parents=[common], help="revoke this computer's token")
    s.set_defaults(fn=cmd_logout)
    s = sub.add_parser("whoami", parents=[common], help="which account this computer is logged in as")
    s.set_defaults(fn=cmd_whoami)

    def ranged(sp, default_days: int):
        sp.add_argument("--date", help="one day (YYYY-MM-DD, today, tomorrow, +N)")
        sp.add_argument("--from", dest="from_", help="first day (default today)")
        sp.add_argument("--to", help="last day (inclusive)")
        sp.add_argument("--days", type=int, default=default_days, help=f"number of days when --to is not given (default {default_days})")

    s = sub.add_parser("list", parents=[common], help="show events")
    ranged(s, 7)
    s.add_argument("--query", "-q", help="only events whose title or location contains this")
    s.add_argument("--friend", "-f", help="a friend's calendar instead of yours (name or id from `friends`; read-only)")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("friends", parents=[common], help="your friends (whose calendars you can read with list --friend)")
    s.set_defaults(fn=cmd_friends)

    def fields(sp, title_positional: bool):
        if title_positional:
            sp.add_argument("title", help="what it is")
        else:
            sp.add_argument("--title", help="new title")
        sp.add_argument("--date", help="YYYY-MM-DD, today, tomorrow or +N")
        sp.add_argument("--start", help="HH:MM (24h), or an ISO date-time like 2026-10-25T14:00+08:00")
        sp.add_argument("--end", help="HH:MM (24h; 24:00 = midnight), or an ISO date-time")
        sp.add_argument("--duration", help="instead of --end: 30m, 1h, 1h30m")
        sp.add_argument("--location")
        sp.add_argument("--attendees", help="comma-separated names")
        sp.add_argument("--meeting-url", help="video call link")
        sp.add_argument("--tz", help="time zone for ISO times (default: this computer's)")

    s = sub.add_parser("add", parents=[common], help="add an event")
    fields(s, True)
    s.set_defaults(fn=cmd_add, done=None)

    s = sub.add_parser("update", parents=[common], help="change an event (by id from list)")
    s.add_argument("id")
    fields(s, False)
    s.add_argument("--clear-time", action="store_true", help="make it an all-day / untimed item")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--done", dest="done", action="store_true", default=None, help="tick it off")
    g.add_argument("--not-done", dest="done", action="store_false", help="un-tick it")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("delete", parents=[common], help="delete events (by id from list)")
    s.add_argument("ids", nargs="+", metavar="id")
    s.set_defaults(fn=cmd_delete)

    s = sub.add_parser("import", parents=[common], help="add events from Feishu/Lark JSON, Google JSON or .ics (skips ones already there)")
    s.add_argument("file", help="file path, or - for stdin")
    s.add_argument("--dry-run", action="store_true", help="show what would be added, write nothing")
    s.add_argument("--from", dest="from_", help="only events on or after this day")
    s.add_argument("--to", help="only events on or before this day")
    s.add_argument("--skip-all-day", action="store_true", help="leave out all-day events")
    s.add_argument("--all-day-end", choices=["inclusive", "exclusive"],
                   help="is an all-day event's end date its last day (Feishu: inclusive, default for JSON) or the day after (.ics: exclusive)")
    s.add_argument("--tz", help="time zone to place events in (default: this computer's)")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("export", parents=[common], help="print events as JSON (with ISO times) or .ics, e.g. to copy into Feishu")
    ranged(s, 30)
    s.add_argument("--format", choices=["json", "ics"], default="json")
    s.add_argument("--not-in", help="leave out events already in this JSON/.ics file (same day, start and title)")
    s.add_argument("--all-day-end", choices=["inclusive", "exclusive"], help="for --not-in, as in import")
    s.add_argument("--include-done", action="store_true", help="also export ticked-off items")
    s.add_argument("--tz", help="time zone for the ISO times (default: this computer's)")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("install-skill", parents=[common], help="teach Claude Code / Codex how to use this tool")
    s.add_argument("--claude", action="store_true", help="only ~/.claude/skills")
    s.add_argument("--codex", action="store_true", help="only ~/.codex/skills")
    s.add_argument("--dir", help="a skills folder of your choice")
    s.set_defaults(fn=cmd_install_skill)
    return p


def main(argv: list[str] | None = None) -> None:
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        sys.exit(2)
    try:
        args.fn(args)
    except Fail as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"caloogy-calendar: {e}", file=sys.stderr)
        sys.exit(e.code)
    except ConvertError as e:
        print(f"caloogy-calendar: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
