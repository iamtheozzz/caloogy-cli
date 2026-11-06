"""caloogy-chat — read and send your Caloogy Chat (work.caloogy.com) messages from the terminal (and from Claude Code / Codex).

    caloogy-chat login                         # once: approve in the browser
    caloogy-chat list                          # your conversations, unread first
    caloogy-chat unread                        # every message you haven't read yet
    caloogy-chat read Bob                      # the latest messages with Bob
    caloogy-chat send Bob "running 5 min late"

Run `caloogy-chat <command> --help` for each command.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

from . import __version__

DEFAULT_URL = "https://work.caloogy.com"
SKILL_NAME = "caloogy-chat"
CONV_RE = re.compile(r"[0-9a-f]{12}")
USER_RE = re.compile(r"[0-9a-f]{8}")
MSG_RE = re.compile(r"[0-9a-zA-Z_-]{6,40}")
CALL_LINK = re.compile(r"^https?://(?:(call|meet)\.caloogy\.com|theozhang\.me/(call|meet))/([a-z2-9]{3}-[a-z2-9]{4}-[a-z2-9]{3})/?(?:[?#].*)?$")
DOC_LINK = re.compile(r"^https?://docs\.caloogy\.com/([0-9a-f]{8})/([0-9a-f]{16})/?(?:[?#].*)?$")
SITES = {"call": "https://call.caloogy.com", "meet": "https://meet.caloogy.com"}
MAX_TEXT = 8000


UNSAFE_TEXT = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
UNSAFE_JSON = re.compile("[\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def safe_text(s: str) -> str:
    """Other people's words may hold terminal escapes or text-direction tricks: never pass those to the terminal."""
    return UNSAFE_TEXT.sub("", s)


def safe_json(s: str) -> str:
    """json.dumps already escapes \\x00-\\x1f; escape the rest of what a terminal could act on."""
    return UNSAFE_JSON.sub(lambda m: f"\\u{ord(m.group()):04x}", s)


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

def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "caloogy" / "chat.json"


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
    return checked_url((getattr(args, "url", None) or os.environ.get("CALOOGY_CHAT_URL") or read_config().get("url") or DEFAULT_URL).rstrip("/"))


def token() -> str:
    t = os.environ.get("CALOOGY_CHAT_TOKEN") or read_config().get("token")
    if not t:
        raise Fail("Not logged in. Run: caloogy-chat login", 3)
    return t


# ---------------------------------------------------------------- HTTP

def request(args, method: str, path: str, body=None, auth: bool = True) -> tuple[int, dict]:
    headers = {"User-Agent": f"caloogy-chat/{__version__}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = f"Bearer {token()}"
    req = urllib.request.Request(base_url(args) + path, method=method, headers=headers,
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
            raise Fail(data.get("message") or "Your login was revoked or expired. Run: caloogy-chat login", 3)
        return e.code, data
    except urllib.error.URLError as e:
        raise Fail(f"Can't reach {base_url(args)}: {e.reason}")


def api(args, method: str, path: str, body=None, ok=(200, 201)) -> dict:
    status, data = request(args, method, path, body)
    if status not in ok:
        if status == 404 and not (data.get("message") or data.get("error", "").startswith(("No ", "That"))):
            raise Fail("Not found — no such conversation or message, or you're not in it (run: caloogy-chat list).")
        err = data.get("message") or data.get("error")
        raise Fail(err if err and err not in ("bad request", "not found") else f"HTTP {status}")
    return data


# ---------------------------------------------------------------- output

def emit(args, data, text: str | None = None) -> None:
    if args.json or text is None:
        print(safe_json(json.dumps(data, ensure_ascii=False, indent=2)))
    elif text:
        print(safe_text(text))


def when(ms) -> str | None:
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds") if ms else None


def short_time(ms) -> str:
    if not ms:
        return ""
    t = datetime.fromtimestamp(ms / 1000)
    return t.strftime("%H:%M") if t.date() == date.today() else t.strftime("%m-%d %H:%M")


def name_of(users: dict, uid: str) -> str:
    return ((users.get(uid) or {}).get("name") or "").strip() or uid


class Ctx:
    """who I am plus my conversations and the people in them, fetched once per command"""

    def __init__(self, args):
        self.args = args
        self.me = api(args, "GET", "/api/me")
        data = api(args, "GET", "/api/convs")
        self.convs = sorted(data.get("convs") or [], key=lambda c: c.get("updated") or 0, reverse=True)
        self.users = data.get("users") or {}
        self._friends = None

    @property
    def friends(self) -> dict:
        if self._friends is None:
            f = api(self.args, "GET", "/api/friends")
            self.users.update(f.get("users") or {})
            self._friends = {i: self.users.get(i) or {"id": i} for i in f.get("friends") or []}
        return self._friends

    def others(self, c: dict) -> list[str]:
        return [m for m in c.get("members") or [] if m != self.me["id"]]

    def title(self, c: dict) -> str:
        if c.get("kind") == "group":
            return (c.get("name") or "").strip() or ", ".join(name_of(self.users, u) for u in self.others(c)) or "Group"
        o = self.others(c)
        return name_of(self.users, o[0]) if o else "Just me"

    def dm_with(self, uid: str) -> dict | None:
        return next((c for c in self.convs if c.get("kind") == "dm" and self.others(c) == [uid]), None)


def att_text(a: dict | None) -> str:
    if not a:
        return ""
    k = a.get("kind")
    if k == "call":
        return f"[{'voice call' if a.get('mode') == 'call' else 'video meeting'}] {SITES.get(a.get('mode'), SITES['meet'])}/{a.get('room')}"
    if k == "doc":
        return f"[doc] {a.get('title') or 'Untitled'}  https://docs.caloogy.com/{a.get('owner')}/{a.get('id')}"
    if k == "link":
        return f"[link] {(a.get('title') + '  ') if a.get('title') else ''}{a.get('url')}"
    if k == "html":
        return f"[web page] {a.get('name') or 'page.html'}"
    return f"[{k}]"


def att_json(a: dict | None) -> dict | None:
    if not a:
        return None
    out = {"kind": a.get("kind")}
    if a.get("kind") == "call":
        out.update({"mode": a.get("mode"), "room": a.get("room"), "url": f"{SITES.get(a.get('mode'), SITES['meet'])}/{a.get('room')}"})
    elif a.get("kind") == "doc":
        out.update({"title": a.get("title"), "url": f"https://docs.caloogy.com/{a.get('owner')}/{a.get('id')}"})
    elif a.get("kind") == "link":
        out.update({"title": a.get("title"), "url": a.get("url")})
    elif a.get("kind") == "html":
        out.update({"name": a.get("name"), "size": len(a.get("html") or "")})
    return out


def msg_json(ctx: Ctx, m: dict) -> dict:
    out = {"seq": m.get("seq"), "id": m.get("id"), "from": m.get("from"), "from_name": name_of(ctx.users, m.get("from")),
           "mine": m.get("from") == ctx.me["id"], "time": when(m.get("ts"))}
    if m.get("via"):
        out["via"] = m["via"]
    if m.get("deleted"):
        out["deleted"] = True
    else:
        out["text"] = m.get("text") or ""
        if m.get("att"):
            out["attachment"] = att_json(m["att"])
    return out


def msg_line(ctx: Ctx, m: dict) -> str:
    who = "me" if m.get("from") == ctx.me["id"] else name_of(ctx.users, m.get("from"))
    if m.get("deleted"):
        body = "(deleted)"
    else:
        body = " ".join(x for x in ((m.get("text") or "").strip(), att_text(m.get("att"))) if x)
    pad = " " * (len(short_time(m.get("ts"))) + len(who) + 4)
    return f"{short_time(m.get('ts'))}  {who}: " + body.replace("\n", "\n" + pad)


def conv_json(ctx: Ctx, c: dict) -> dict:
    last = c.get("last")
    return {"id": c["id"], "kind": c.get("kind"), "title": ctx.title(c), "unread": c.get("unread") or 0,
            "members": [{"id": u, "name": name_of(ctx.users, u)} for u in c.get("members") or []],
            "updated": when(c.get("updated")), "last": msg_json(ctx, last) if last else None}


# ---------------------------------------------------------------- finding a conversation or a person

def find_person(ctx: Ctx, ref: str) -> str:
    """an account id from an 8-character id or a name (people I chat with or my friends)"""
    r = ref.strip()
    if USER_RE.fullmatch(r.lower()):
        return r.lower()
    if r.lower() in ("me", "myself"):
        return ctx.me["id"]
    ids = {u for c in ctx.convs for u in ctx.others(c)} | set(ctx.friends)
    key = r.casefold()
    exact = sorted(u for u in ids if name_of(ctx.users, u).casefold() == key)
    hits = exact or sorted(u for u in ids if key in name_of(ctx.users, u).casefold())
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise Fail(f"Nobody called {ref!r} among your friends and chats (caloogy-chat friends). An 8-character account id works too.", 1)
    raise Fail(f"{ref!r} could be: " + ", ".join(f"{name_of(ctx.users, u)} ({u})" for u in hits) + " — use the id.", 1)


def find_conv(ctx: Ctx, ref: str, create: bool = False) -> dict:
    """a conversation from its 12-character id, a group's name, or a person (id or name) = the direct chat with them"""
    r = ref.strip()
    if CONV_RE.fullmatch(r.lower()):
        c = next((c for c in ctx.convs if c["id"] == r.lower()), None)
        if not c:
            raise Fail(f"No conversation {r} (run: caloogy-chat list).", 1)
        return c
    if not USER_RE.fullmatch(r.lower()):
        key = r.casefold()
        groups = [c for c in ctx.convs if c.get("kind") == "group" and (c.get("name") or "").strip().casefold() == key]
        if len(groups) == 1:
            return groups[0]
        if len(groups) > 1:
            raise Fail(f"Several groups are called {ref!r}: " + ", ".join(c["id"] for c in groups) + " — use the id.", 1)
    uid = find_person(ctx, r)
    if uid == ctx.me["id"]:
        raise Fail("That's you.", 2)
    c = ctx.dm_with(uid)
    if c:
        return c
    if not create:
        raise Fail(f"You have no chat with {name_of(ctx.users, uid)} yet — send them a message to start one.", 1)
    data = api(ctx.args, "POST", "/api/convs", {"with": uid})
    ctx.users.update(data.get("users") or {})
    ctx.convs.insert(0, data["conv"])
    return data["conv"]


def messages(args, cid: str, limit: int | None = None, after: int | None = None) -> list[dict]:
    """the latest `limit` messages (oldest first), or every message after seq `after`"""
    if after is not None:
        out, more = [], True
        while more:
            d = api(args, "GET", f"/api/convs/{cid}/msgs?after={after}")
            out += d.get("msgs") or []
            more = bool(d.get("more")) and bool(out)
            after = out[-1]["seq"] if out else after
        return out if limit is None else out[-limit:]
    out, before = [], None
    while True:
        d = api(args, "GET", f"/api/convs/{cid}/msgs" + (f"?before={before}" if before else ""))
        batch = d.get("msgs") or []
        out = batch + out
        if not d.get("more") or not batch or (limit is not None and len(out) >= limit):
            break
        before = batch[0]["seq"]
    return out if limit is None else out[-limit:]


def mark_read(args, c: dict) -> None:
    if c.get("seq"):
        api(args, "POST", f"/api/convs/{c['id']}/read", {"seq": c["seq"]})


# ---------------------------------------------------------------- commands

def cmd_login(args) -> None:
    url = base_url(args)
    if args.device_code:
        device = {"device_code": args.device_code, "interval": 2, "expires_in": 600}
    else:
        name = args.name or f"caloogy-chat on {socket.gethostname().split('.')[0] or platform.node()}"
        status, device = request(args, "POST", "/api/cli/start", {"name": name, "scope": "write" if args.write else "read"}, auth=False)
        if status != 200:
            raise Fail(device.get("message") or f"Couldn't start a login (HTTP {status}).")
        if args.no_wait:
            emit(args, {"verify_url": device["verify_url"], "user_code": device["user_code"],
                        "device_code": device["device_code"], "expires_in": device["expires_in"],
                        "next": f"caloogy-chat login --device-code {device['device_code']}"},
                 f"Open this link, check the code and choose Allow:\n\n  {device['verify_url']}\n  code: {device['user_code']}\n\n"
                 f"Then run:\n  caloogy-chat login --device-code {device['device_code']}")
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
        status, r = request(args, "POST", "/api/cli/poll", {"device_code": device["device_code"]}, auth=False)
        st = r.get("status")
        if status == 200 and st == "ok":
            cfg = read_config()
            cfg.update({"token": r["token"], "url": url, "account": r.get("account") or {}})
            write_config(cfg)
            acct = r.get("account") or {}
            scope = r.get("scope") or "read"
            emit(args, {"ok": True, "account": acct, "scope": scope, "config": str(config_path())},
                 f"Logged in as {acct.get('name') or acct.get('id')} (id {acct.get('id')}), "
                 + ("can read and send." if scope == "write" else "read-only. To send messages too: caloogy-chat login --write"))
            return
        if st == "denied":
            raise Fail("The login was denied in the browser.")
        if st == "expired":
            raise Fail("The login link expired. Run caloogy-chat login again.")
        if status == 429:
            time.sleep(10)
        time.sleep(float(device.get("interval") or 2))
    raise Fail("Timed out waiting for approval. Run caloogy-chat login again.")


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
    emit(args, {**me, "url": base_url(args)}, f"{me.get('name') or me['id']} (id {me['id']}) on {base_url(args)}, {'can read and send' if me.get('scope') == 'write' else 'read-only'}")


def cmd_list(args) -> None:
    ctx = Ctx(args)
    convs = [c for c in ctx.convs if not args.unread or c.get("unread")]
    if args.query:
        q = args.query.casefold()
        convs = [c for c in convs if q in ctx.title(c).casefold()]
    convs = sorted(convs, key=lambda c: (not c.get("unread"),))[: args.limit]      # unread first, then newest
    lines = []
    for c in convs:
        last = c.get("last")
        prev = ""
        if last:
            who = "me" if last.get("from") == ctx.me["id"] else name_of(ctx.users, last.get("from")).split()[0]
            body = "(deleted)" if last.get("deleted") else ((last.get("text") or "").strip() or att_text(last.get("att")))
            body = " ".join(body.split())
            prev = f"{who}: {body[:60]}{'…' if len(body) > 60 else ''}"
        badge = f"  [{c['unread']} new]" if c.get("unread") else ""
        kind = "group " if c.get("kind") == "group" else ""
        lines.append(f"  {c['id']}  {kind}{ctx.title(c)}{badge}   {short_time(c.get('updated'))}\n      {prev}".rstrip())
    emit(args, {"me": {"id": ctx.me["id"], "name": ctx.me.get("name")}, "convs": [conv_json(ctx, c) for c in convs]},
         "\n".join(lines) or ("No unread messages." if args.unread else "No conversations yet."))


def cmd_read(args) -> None:
    ctx = Ctx(args)
    c = find_conv(ctx, args.conv)
    msgs = messages(args, c["id"], None if args.all else args.limit)
    if args.mark_read:
        mark_read(args, c)
    emit(args, {"conv": conv_json(ctx, c), "messages": [msg_json(ctx, m) for m in msgs]},
         f"— {ctx.title(c)} ({c['id']})\n" + ("\n".join(msg_line(ctx, m) for m in msgs) or "No messages yet."))


def cmd_unread(args) -> None:
    ctx = Ctx(args)
    out, lines = [], []
    for c in ctx.convs:
        if not c.get("unread"):
            continue
        seen = (c.get("reads") or {}).get(ctx.me["id"]) or 0
        new = [m for m in messages(args, c["id"], after=seen) if m.get("from") != ctx.me["id"] and not m.get("deleted")]
        if not new:
            continue
        if args.mark_read:
            mark_read(args, c)
        out.append({"conv": conv_json(ctx, c), "messages": [msg_json(ctx, m) for m in new]})
        lines.append(f"— {ctx.title(c)} ({c['id']}), {len(new)} new\n" + "\n".join(msg_line(ctx, m) for m in new))
    emit(args, {"unread": out, "marked_read": bool(args.mark_read)},
         "\n\n".join(lines) + ("\n\n(marked as read)" if lines and args.mark_read else "") if lines else "No unread messages.")


def attachment(args) -> dict | None:
    given = [x for x in (args.call, args.doc, args.link) if x]
    if len(given) > 1:
        raise Fail("Attach one thing at a time: --call, --doc or --link.", 2)
    if args.call:
        m = CALL_LINK.match(args.call.strip())
        if not m:
            raise Fail("--call takes a call.caloogy.com or meet.caloogy.com room link (from caloogy-call new / caloogy-meet new).", 2)
        return {"kind": "call", "mode": m[1] or m[2], "room": m[3]}
    if args.doc:
        m = DOC_LINK.match(args.doc.strip())
        if not m:
            raise Fail("--doc takes a document link like https://docs.caloogy.com/<owner>/<id> (from caloogy-docs list --json).", 2)
        return {"kind": "doc", "owner": m[1], "id": m[2], "title": args.title or "Document"}
    if args.link:
        if not re.match(r"^https?://\S{1,2000}$", args.link.strip()):
            raise Fail("--link takes an http(s) address.", 2)
        return {"kind": "link", "url": args.link.strip(), "title": args.title or ""}
    return None


def confirm_file(args) -> None:
    """A file's contents leave this computer: only a person at the terminal may say so."""
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        raise Fail("Sending a file needs a person at the terminal to confirm it. Ask the user to run this command themselves.", 2)
    print(f"Send the contents of {args.file} to {args.to}? [y/N] ", end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        raise Fail("Not sent.")


def cmd_send(args) -> None:
    if args.text is not None and args.file is not None:
        raise Fail("Give the message as text or with --file, not both.", 2)
    text = args.text
    if args.file is not None:
        try:
            if args.file == "-":
                text = sys.stdin.read()
            else:
                confirm_file(args)
                text = Path(args.file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise Fail(f"Can't read {args.file}: {e.strerror}", 2)
    text = (text or "").strip("\n")
    att = attachment(args)
    if not text.strip() and not att:
        raise Fail("Nothing to send — give the message text (or --file -), or attach --call / --doc / --link.", 2)
    if len(text) > MAX_TEXT:
        raise Fail(f"That message is {len(text)} characters; the limit is {MAX_TEXT}. Split it, or share it as a Caloogy doc.", 2)
    ctx = Ctx(args)
    c = find_conv(ctx, args.to, create=True)
    body = {"id": secrets.token_urlsafe(12), "text": text}
    if att:
        body["att"] = att
    m = api(args, "POST", f"/api/convs/{c['id']}/msgs", body)["msg"]
    emit(args, {"ok": True, "conv": c["id"], "to": ctx.title(c), "message": msg_json(ctx, m)},
         f"Sent to {ctx.title(c)} ({c['id']}).")


def cmd_mark_read(args) -> None:
    ctx = Ctx(args)
    targets = [c for c in ctx.convs if c.get("unread")] if args.all else [find_conv(ctx, args.conv)] if args.conv else None
    if targets is None:
        raise Fail("Name a conversation, or pass --all.", 2)
    for c in targets:
        mark_read(args, c)
    emit(args, {"ok": True, "marked": [c["id"] for c in targets]},
         "\n".join(f"Marked {ctx.title(c)} as read." for c in targets) or "Nothing unread.")


def cmd_delete(args) -> None:
    ctx = Ctx(args)
    c = find_conv(ctx, args.conv)
    if not MSG_RE.fullmatch(args.msg):
        raise Fail("That's not a message id (read --json shows them).", 2)
    status, r = request(args, "DELETE", f"/api/convs/{c['id']}/msgs/{args.msg}")
    if status == 404:
        raise Fail("No such message of yours in that conversation — you can only delete your own.")
    if status != 200:
        raise Fail(r.get("error") or f"HTTP {status}")
    emit(args, {"ok": True, "conv": c["id"], "deleted": args.msg}, f"Deleted the message in {ctx.title(c)}.")


def cmd_friends(args) -> None:
    f = api(args, "GET", "/api/friends")
    users = f.get("users") or {}
    friends = sorted(({"id": i, "name": name_of(users, i)} for i in f.get("friends") or []), key=lambda u: u["name"].casefold())
    inc = [{"id": x["id"], "name": name_of(users, x["id"]), "since": when(x.get("ts"))} for x in f.get("incoming") or []]
    out = [{"id": x["id"], "name": name_of(users, x["id"]), "since": when(x.get("ts"))} for x in f.get("outgoing") or []]
    lines = ["Friends" + ("" if friends else ": none")] + [f"  {u['id']}  {u['name']}" for u in friends]
    if inc:
        lines += ["Asked to be your friend (accept on the website)"] + [f"  {u['id']}  {u['name']}" for u in inc]
    if out:
        lines += ["Waiting for them to accept"] + [f"  {u['id']}  {u['name']}" for u in out]
    emit(args, {"friends": friends, "incoming": inc, "outgoing": out}, "\n".join(lines))


def cmd_whois(args) -> None:
    uid = args.id.strip().lower()
    if not USER_RE.fullmatch(uid):
        raise Fail("An account id is 8 characters, 0-9 and a-f.", 2)
    u = api(args, "GET", f"/api/users/{uid}")
    rel = {"yes": "your friend", "sent": "you asked them to be friends", "received": "they asked to be your friend", "no": "not your friend"}
    emit(args, {"id": u["id"], "name": u.get("name"), "friend": u.get("friend")},
         f"{u.get('name') or u['id']} (id {u['id']}) — {rel.get(u.get('friend'), u.get('friend'))}")


def cmd_busy(args) -> None:
    ctx = Ctx(args)
    uid = find_person(ctx, args.person)
    try:
        start = date.fromisoformat(args.start) if args.start else date.today()
    except ValueError:
        raise Fail("--from is a date like 2026-11-05.", 2)
    if not 1 <= args.days <= 31:
        raise Fail("--days is 1 to 31.", 2)
    end = start + timedelta(days=args.days - 1)
    d = api(args, "GET", f"/api/busy/{uid}?from={start.isoformat()}&to={end.isoformat()}")
    hm = lambda m: f"{m // 60:02d}:{m % 60:02d}"
    days = {k: [[hm(a), hm(b)] for a, b in v] for k, v in sorted((d.get("days") or {}).items())}
    who = "You" if uid == ctx.me["id"] else name_of(ctx.users, uid)
    lines = [f"{who} — busy times, {start} to {end}" + (f" ({d['tz']})" if d.get("tz") else "")]
    for i in range(args.days):
        k = (start + timedelta(days=i)).isoformat()
        slots = days.get(k) or []
        lines.append(f"  {k} {date.fromisoformat(k).strftime('%a')}  " + (", ".join(f"{a}–{b}" for a, b in slots) if slots else "free"))
    emit(args, {"id": uid, "name": None if uid == ctx.me["id"] else name_of(ctx.users, uid), "tz": d.get("tz"),
                "from": start.isoformat(), "to": end.isoformat(), "busy": days}, "\n".join(lines))


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
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output (for scripts and AI tools)")
    common.add_argument("--url", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(prog="caloogy-chat", description="Read and send your Caloogy Chat (work.caloogy.com) messages.",
                                epilog="CONV is a conversation's 12-character id, a group's name, or a person "
                                       "(their name or 8-character account id) for your direct chat with them.")
    p.add_argument("--json", action="store_true", help="machine-readable output (for scripts and AI tools)")
    p.add_argument("--url", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"caloogy-chat {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    s = sub.add_parser("login", parents=[common], help="connect this computer to your account (approve in the browser)")
    s.add_argument("--name", help="how this tool shows up under Command-line access")
    s.add_argument("--write", action="store_true", help="also let this login send messages, mark chats read and delete your own messages (default: read-only)")
    s.add_argument("--no-browser", action="store_true", help="just print the link")
    s.add_argument("--no-wait", action="store_true", help="print the link and a device code, then exit (finish with --device-code)")
    s.add_argument("--device-code", help="finish a login started with --no-wait")
    s.set_defaults(fn=cmd_login)
    s = sub.add_parser("logout", parents=[common], help="revoke this computer's token")
    s.set_defaults(fn=cmd_logout)
    s = sub.add_parser("whoami", parents=[common], help="which account this computer is logged in as")
    s.set_defaults(fn=cmd_whoami)

    s = sub.add_parser("list", parents=[common], help="your conversations, unread first, then newest")
    s.add_argument("--unread", action="store_true", help="only conversations with unread messages")
    s.add_argument("-q", "--query", help="only conversations whose name contains this")
    s.add_argument("-n", "--limit", type=int, default=50, help="at most this many (default 50)")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("unread", parents=[common], help="every message you haven't read yet, by conversation")
    s.add_argument("--mark-read", action="store_true", help="then mark them as read")
    s.set_defaults(fn=cmd_unread)

    s = sub.add_parser("read", parents=[common], help="the latest messages in a conversation")
    s.add_argument("conv", metavar="CONV")
    g = s.add_mutually_exclusive_group()
    g.add_argument("-n", "--limit", type=int, default=30, help="how many (default 30)")
    g.add_argument("--all", action="store_true", help="the whole history")
    s.add_argument("--mark-read", action="store_true", help="mark the conversation as read")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("send", parents=[common], help="send a message (to a person: starts your chat with them if needed)")
    s.add_argument("to", metavar="CONV")
    s.add_argument("text", nargs="?", metavar="TEXT")
    s.add_argument("--file", "-f", help="read the message from this file (- = stdin)")
    s.add_argument("--call", metavar="LINK", help="attach a call.caloogy.com / meet.caloogy.com room link as a join card")
    s.add_argument("--doc", metavar="LINK", help="attach a docs.caloogy.com document link")
    s.add_argument("--link", metavar="URL", help="attach any web link")
    s.add_argument("--title", help="the title shown for --doc / --link")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("mark-read", parents=[common], help="mark a conversation (or --all) as read")
    s.add_argument("conv", nargs="?", metavar="CONV")
    s.add_argument("--all", action="store_true", help="every conversation")
    s.set_defaults(fn=cmd_mark_read)

    s = sub.add_parser("delete", parents=[common], help="delete one of your own messages")
    s.add_argument("conv", metavar="CONV")
    s.add_argument("msg", metavar="MESSAGE_ID")
    s.set_defaults(fn=cmd_delete)

    s = sub.add_parser("friends", parents=[common], help="your friends and open friend requests")
    s.set_defaults(fn=cmd_friends)
    s = sub.add_parser("whois", parents=[common], help="look up an account by its 8-character id")
    s.add_argument("id", metavar="ID")
    s.set_defaults(fn=cmd_whois)

    s = sub.add_parser("busy", parents=[common], help="when a friend (or you) is busy, from their Caloogy calendar")
    s.add_argument("person", metavar="PERSON", help="a name, an account id, or me")
    s.add_argument("--from", dest="start", metavar="DATE", help="first day (default today)")
    s.add_argument("--days", type=int, default=7, help="how many days (default 7, at most 31)")
    s.set_defaults(fn=cmd_busy)

    s = sub.add_parser("install-skill", parents=[common], help="teach Claude Code / Codex how to use this tool")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--claude", action="store_true", help="only ~/.claude/skills")
    g.add_argument("--codex", action="store_true", help="only ~/.codex/skills")
    g.add_argument("--dir", help="another skills folder")
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
            print(safe_json(json.dumps({"error": str(e)}, ensure_ascii=False)))
        else:
            print(safe_text(f"caloogy-chat: {e}"), file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
