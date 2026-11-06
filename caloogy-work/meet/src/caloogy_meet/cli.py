"""caloogy-meet and caloogy-call — make and list your Caloogy Meet rooms from the terminal (and from Claude Code / Codex).
caloogy-meet is for video meetings (meet.caloogy.com), caloogy-call for voice calls (call.caloogy.com).

    caloogy-call login                 # once: approve in the browser
    caloogy-call new                   # a new voice-call link to send someone
    caloogy-meet new --open            # a new video meeting, opened in the browser
    caloogy-meet list                  # your meetings: upcoming (nobody joined yet) and recent
    caloogy-meet show abc-defg-hjk     # is anyone in it right now?

Run `caloogy-meet <command> --help` for each command.
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
from datetime import datetime
from pathlib import Path

from . import __version__

R = "[a-km-np-z2-9]"                                   # the server's alphabet: no l, o, 0 or 1
ROOM_RE = re.compile(rf"(?<![a-z0-9])({R}{{3}}-{R}{{4}}-{R}{{3}})(?![a-z0-9])")


class Tool:
    def __init__(self, kind: str):
        self.kind = kind
        self.prog = f"caloogy-{kind}"
        self.site = f"https://{kind}.caloogy.com"
        self.env = f"CALOOGY_{kind.upper()}"
        self.what = "video meeting" if kind == "meet" else "voice call"
        self.whats = self.what + "s"
        self.other = "call" if kind == "meet" else "meet"


TOOLS = {"meet": Tool("meet"), "call": Tool("call")}


class Fail(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


ALLOWED_DOMAINS = ("caloogy.com", "theozhang.me")


def checked_url(url: str) -> str:
    """Your token only ever goes to Caloogy. A --url, environment variable or config file pointing anywhere else (say, one
    an AI tool was talked into using by a message it read) is refused rather than sent the token."""
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    local = p.scheme == "http" and (host in ("localhost", "127.0.0.1") or host.endswith(".localhost"))
    ours = p.scheme == "https" and any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)
    if not (local or ours) or p.username or p.password:
        raise Fail(f"Refusing to use {url!r}: only https://*.caloogy.com is allowed, so your token can't be sent anywhere else.", 2)
    return url


class _StayOnHost(urllib.request.HTTPRedirectHandler):
    """urllib would carry the Authorization header along on a redirect to any host; ours never leave for another site."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            new = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new is not None:
                new.remove_header("Authorization")
            return new
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_StayOnHost)


# ---------------------------------------------------------------- config

def config_path(t: Tool) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "caloogy" / f"{t.kind}.json"


def read_config(t: Tool) -> dict:
    try:
        return json.loads(config_path(t).read_text())
    except (OSError, ValueError):
        return {}


def write_config(t: Tool, cfg: dict) -> None:
    p = config_path(t)
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
    t = args.tool
    return checked_url((getattr(args, "url", None) or os.environ.get(f"{t.env}_URL") or read_config(t).get("url") or t.site).rstrip("/"))


def token(t: Tool) -> str:
    v = os.environ.get(f"{t.env}_TOKEN") or read_config(t).get("token")
    if not v:
        raise Fail(f"Not logged in. Run: {t.prog} login", 3)
    return v


# ---------------------------------------------------------------- HTTP

def request(args, method: str, path: str, body=None, auth: bool = True) -> tuple[int, dict]:
    t = args.tool
    headers = {"User-Agent": f"{t.prog}/{__version__}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = f"Bearer {token(t)}"
    req = urllib.request.Request(base_url(args) + "/meet/api" + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with _OPENER.open(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except ValueError:
            data = {}
        if e.code == 401 and auth:
            raise Fail(f"Your login was revoked or expired. Run: {t.prog} login", 3)
        return e.code, data
    except urllib.error.URLError as e:
        raise Fail(f"Can't reach {base_url(args)}: {e.reason}")


def api(args, method: str, path: str, body=None, ok=(200, 201)) -> dict:
    status, data = request(args, method, path, body)
    if status not in ok:
        if status == 429:
            raise Fail("Too many new rooms in the last hour — wait a while, or reuse one from the list.")
        err = data.get("message") or data.get("error")
        raise Fail(err if err else f"HTTP {status}")
    return data


# ---------------------------------------------------------------- output

UNSAFE_TEXT = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
UNSAFE_JSON = re.compile("[\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def safe_text(s: str) -> str:
    return UNSAFE_TEXT.sub("", s)


def safe_json(s: str) -> str:
    return UNSAFE_JSON.sub(lambda m: f"\\u{ord(m.group()):04x}", s)


def emit(args, data, text: str | None = None) -> None:
    if args.json or text is None:
        print(safe_json(json.dumps(data, ensure_ascii=False, indent=2)))
    elif text:
        print(safe_text(text))


def when(ts) -> str | None:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def ago(ts) -> str:
    d = time.time() - (ts or 0)
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{round(d / 60)} min ago"
    if d < 86400:
        return f"{round(d / 3600)} h ago"
    return f"{round(d / 86400)} days ago"


def link(args, kind: str, rid: str) -> str:
    base = base_url(args)
    if kind != args.tool.kind and base == args.tool.site:      # a room of the other kind opens on its own site
        base = TOOLS[kind].site
    return f"{base}/{rid}"


def room_id(ref: str) -> str:
    """a room from its code (abc-defg-hjk) or its link (https://meet.caloogy.com/abc-defg-hjk)"""
    m = ROOM_RE.search((ref or "").strip().lower())
    if not m:
        raise Fail(f"Not a room code or link: {ref!r} (like abc-defg-hjk)", 2)
    return m[1]


# ---------------------------------------------------------------- commands

def cmd_login(args) -> None:
    t = args.tool
    url = base_url(args)
    if args.device_code:
        device = {"device_code": args.device_code, "interval": 2, "expires_in": 600}
    else:
        name = args.name or f"{t.prog} on {socket.gethostname().split('.')[0] or platform.node()}"
        status, device = request(args, "POST", "/cli/start", {"name": name, "kind": t.kind}, auth=False)
        if status != 200:
            raise Fail(device.get("message") or f"Couldn't start a login (HTTP {status}).")
        if args.no_wait:
            emit(args, {"verify_url": device["verify_url"], "user_code": device["user_code"],
                        "device_code": device["device_code"], "expires_in": device["expires_in"],
                        "next": f"{t.prog} login --device-code {device['device_code']}"},
                 f"Open this link, check the code and choose Allow:\n\n  {device['verify_url']}\n  code: {device['user_code']}\n\n"
                 f"Then run:\n  {t.prog} login --device-code {device['device_code']}")
            return
        print(f"Open this link in your browser, check the code and choose Allow:\n\n  {device['verify_url']}\n\n"
              f"  code: {device['user_code']}\n\nWaiting for approval (up to 10 minutes)...", file=sys.stderr, flush=True)
        if not args.no_browser:
            try:
                webbrowser.open(checked_url(device["verify_url"]))
            except Exception:
                pass
    deadline = time.time() + float(device.get("expires_in") or 600)
    while time.time() < deadline:
        status, r = request(args, "POST", "/cli/poll", {"device_code": device["device_code"]}, auth=False)
        st = r.get("status")
        if status == 200 and st == "ok":
            cfg = read_config(t)
            cfg.update({"token": r["token"], "url": url, "account": r.get("account") or {}})
            write_config(t, cfg)
            acct = r.get("account") or {}
            emit(args, {"ok": True, "account": acct, "kind": r.get("kind"), "config": str(config_path(t))},
                 f"Logged in as {acct.get('name') or acct.get('id')}.")
            return
        if st == "denied":
            raise Fail("The login was denied in the browser.")
        if st == "expired":
            raise Fail(f"The login link expired. Run {t.prog} login again.")
        if status == 429:
            time.sleep(10)
        time.sleep(float(device.get("interval") or 2))
    raise Fail(f"Timed out waiting for approval. Run {t.prog} login again.")


def cmd_logout(args) -> None:
    t = args.tool
    cfg = read_config(t)
    if cfg.get("token"):
        try:
            request(args, "DELETE", "/cli/tokens/self")
        except Fail:
            pass
    cfg.pop("token", None)
    cfg.pop("account", None)
    write_config(t, cfg)
    emit(args, {"ok": True}, "Logged out (the token was revoked).")


def cmd_whoami(args) -> None:
    me = api(args, "GET", "/me")
    emit(args, {"id": me.get("id"), "name": me.get("name"), "kind": me.get("kind"), "url": base_url(args)},
         f"{me.get('name') or me.get('id')} (id {me.get('id')}) on {base_url(args)}")


def cmd_new(args) -> None:
    t = args.tool
    r = api(args, "POST", "/rooms", {"kind": t.kind})
    url = link(args, t.kind, r["id"])
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    emit(args, {"ok": True, "id": r["id"], "kind": t.kind, "url": url},
         f"New {t.what}: {url}\n  Send the link to the other person; whoever opens it first waits for the other. "
         f"Two people per room, both signed in to Caloogy.")


def room_json(args, r: dict) -> dict:
    return {"id": r["id"], "url": link(args, args.tool.kind, r["id"]), "created": when(r.get("created")),
            "last_used": when(r.get("last_used")), "used": bool(r.get("used")), "in_room_now": r.get("count") or 0}


def cmd_list(args) -> None:
    t = args.tool
    rooms = api(args, "GET", f"/rooms?kind={t.kind}").get("rooms") or []
    up = [r for r in rooms if not r.get("used") and not r.get("count")]
    recent = [r for r in rooms if r.get("used") or r.get("count")]
    up.sort(key=lambda r: r.get("created") or 0, reverse=True)
    show_up, show_recent = not args.recent, not args.upcoming
    lines = []
    if show_up:
        lines.append("Upcoming (nobody has joined yet)" + ("" if up else ": none"))
        lines += [f"  {link(args, t.kind, r['id'])}   made {ago(r.get('created'))}" for r in up[: args.limit]]
    if show_recent:
        lines.append("Recent" + ("" if recent else ": none"))
        lines += [f"  {link(args, t.kind, r['id'])}   " + (f"{r['count']} in it now" if r.get("count") else f"last used {ago(r.get('last_used'))}")
                  for r in recent[: args.limit]]
    emit(args, {"kind": t.kind,
                "upcoming": [room_json(args, r) for r in up[: args.limit]] if show_up else [],
                "recent": [room_json(args, r) for r in recent[: args.limit]] if show_recent else []}, "\n".join(lines))


def cmd_show(args) -> None:
    rid = room_id(args.room)
    status, r = request(args, "GET", f"/rooms/{rid}")
    if status == 404:
        raise Fail(f"No room {rid} — the code is wrong, or it went unused for 30 days and was deleted.")
    if status != 200:
        raise Fail(r.get("message") or r.get("error") or f"HTTP {status}")
    kind = r.get("kind") or args.tool.kind
    url = link(args, kind, rid)
    what = TOOLS[kind].what if kind in TOOLS else kind
    if r.get("locked"):
        emit(args, {"id": rid, "kind": kind, "url": url, "locked": True},
             f"{url}  ({what}) — it belongs to two other people; you can't join it.")
        return
    n, cap = r.get("count") or 0, r.get("capacity") or 2
    emit(args, {"id": rid, "kind": kind, "url": url, "locked": False, "in_room_now": n, "capacity": cap},
         f"{url}  ({what}) — " + ("nobody in it right now" if not n else f"{n} of {cap} in it right now"))


def cmd_open(args) -> None:
    rid = room_id(args.room)
    status, r = request(args, "GET", f"/rooms/{rid}")
    if status == 404:
        raise Fail(f"No room {rid}.")
    url = link(args, r.get("kind") or args.tool.kind, rid)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    emit(args, {"ok": True, "url": url}, f"Opening {url}")


def skill_text(t: Tool) -> str:
    return (Path(__file__).with_name(f"SKILL-{t.kind}.md")).read_text(encoding="utf-8")


def cmd_install_skill(args) -> None:
    t = args.tool
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
    for base in targets:
        d = base / t.prog
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(skill_text(t), encoding="utf-8")
        written.append(str(d / "SKILL.md"))
    emit(args, {"written": written}, "Installed the skill for your AI tools:\n" + "\n".join(f"  {w}" for w in written)
         + "\nRestart Claude Code / Codex so they pick it up.")


# ---------------------------------------------------------------- argument parsing

def build_parser(t: Tool) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output (for scripts and AI tools)")
    common.add_argument("--url", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(prog=t.prog, description=f"Make and list your Caloogy {t.whats} ({t.site.split('//')[1]}).",
                                epilog=f"ROOM is a room code (abc-defg-hjk) or its link. For {TOOLS[t.other].whats} use {TOOLS[t.other].prog}.")
    p.add_argument("--json", action="store_true", help="machine-readable output (for scripts and AI tools)")
    p.add_argument("--url", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"{t.prog} {__version__}")
    p.set_defaults(tool=t)
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

    s = sub.add_parser("new", parents=[common], help=f"make a new {t.what} link")
    s.add_argument("--open", action="store_true", help="and open it in the browser")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("list", parents=[common], help=f"your {t.whats}: upcoming (nobody joined yet) and recent")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--upcoming", action="store_true", help="only rooms nobody has joined yet")
    g.add_argument("--recent", action="store_true", help="only rooms that have been used")
    s.add_argument("-n", "--limit", type=int, default=10, help="at most this many of each (default 10)")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", parents=[common], help="a room's link, and whether anyone is in it now")
    s.add_argument("room", metavar="ROOM")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("open", parents=[common], help="open a room in the browser")
    s.add_argument("room", metavar="ROOM")
    s.set_defaults(fn=cmd_open)

    s = sub.add_parser("install-skill", parents=[common], help="teach Claude Code / Codex how to use this tool")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--claude", action="store_true", help="only ~/.claude/skills")
    g.add_argument("--codex", action="store_true", help="only ~/.codex/skills")
    g.add_argument("--dir", help="another skills folder")
    s.set_defaults(fn=cmd_install_skill)
    return p


def main(kind: str = "meet", argv: list[str] | None = None) -> None:
    t = TOOLS[kind]
    p = build_parser(t)
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        sys.exit(2)
    try:
        args.fn(args)
    except Fail as e:
        if getattr(args, "json", False):
            print(safe_json(json.dumps({"error": str(e)}, ensure_ascii=False)))
        else:
            print(safe_text(f"{t.prog}: {e}"), file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)


def main_meet() -> None:
    main("meet")


def main_call() -> None:
    main("call")
