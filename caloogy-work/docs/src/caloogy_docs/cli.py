"""caloogy-docs — read and write your docs.caloogy.com documents from the terminal (and from Claude Code / Codex).

    caloogy-docs login                           # once: approve in the browser
    caloogy-docs list                            # yours + shared with you
    caloogy-docs read <id or link>               # the Markdown
    caloogy-docs new "Plan" --file plan.md
    caloogy-docs edit <id> --old "draft" --new "final"

Run `caloogy-docs <command> --help` for each command.
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

DEFAULT_URL = "https://docs.caloogy.com"
SKILL_NAME = "caloogy-docs"
DOC_ID = re.compile(r"(?:^|/)([0-9a-f]{16})(?:[/?#]|$)")
ROLE_TXT = {"owner": "owner", "manage": "can manage", "edit": "can edit", "view": "can view", "reader": "can view"}
LEVEL_TXT = {1: "public", 2: "anyone signed in", 3: "people invited", 4: "only me"}


class Fail(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- config

def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "caloogy" / "docs.json"


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
    return (getattr(args, "url", None) or os.environ.get("CALOOGY_DOCS_URL") or read_config().get("url") or DEFAULT_URL).rstrip("/")


def token() -> str:
    t = os.environ.get("CALOOGY_DOCS_TOKEN") or read_config().get("token")
    if not t:
        raise Fail("Not logged in. Run: caloogy-docs login", 3)
    return t


# ---------------------------------------------------------------- HTTP

def request(args, method: str, path: str, body=None, auth: bool = True) -> tuple[int, dict]:
    headers = {"User-Agent": f"caloogy-docs/{__version__}", "Accept": "application/json"}
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
            raise Fail(data.get("message") or "Your login was revoked or expired. Run: caloogy-docs login", 3)
        return e.code, data
    except urllib.error.URLError as e:
        raise Fail(f"Can't reach {base_url(args)}: {e.reason}")


def message(status: int, data: dict) -> str:
    if status == 404:
        return "No such document, or you don't have access to it (run: caloogy-docs list)."
    if status == 413:
        return "That's too large (documents are limited to about 4 MB)."
    err = data.get("message") or data.get("error")
    return err if err and err not in ("bad-request", "not-found") else f"HTTP {status}"


def api(args, method: str, path: str, body=None, ok=(200, 201)) -> dict:
    status, data = request(args, method, path, body)
    if status not in ok:
        raise Fail(message(status, data))
    return data


# ---------------------------------------------------------------- output

def emit(args, data, text: str | None = None) -> None:
    if args.json or text is None:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif text:
        print(text)


def when(ts) -> str | None:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def link(args, owner: str, did: str) -> str:
    return f"{base_url(args)}/{owner}/{did}"


def summary(args, d: dict, me: str | None = None, role: str | None = None) -> dict:
    """a list entry: what an AI needs to pick a document"""
    owner = d.get("owner") or me
    out = {"id": d["id"], "title": d.get("title") or "", "url": link(args, owner, d["id"]), "owner": owner,
           "role": role or d.get("role") or "owner", "updated": when(d.get("updated")), "rev": d.get("rev")}
    if d.get("ownerUser"):
        out["owner_name"] = d["ownerUser"].get("name")
    if d.get("level"):
        out["level"] = d["level"]
    return out


def full(args, d: dict) -> dict:
    out = summary(args, d)
    out.update({"content": d.get("content", ""), "created": when(d.get("created")), "can_write": d.get("role") in WRITERS})
    return out


def title_of(d: dict) -> str:
    return (d.get("title") or "").strip() or "Untitled"


# ---------------------------------------------------------------- documents

def doc_id(ref: str) -> str:
    """a document from its 16-character id, its link (https://docs.caloogy.com/<owner>/<id>) or <owner>/<id>"""
    r = (ref or "").strip().lower()
    m = DOC_ID.search(r)
    if not m:
        raise Fail(f"Not a document id or link: {ref!r} (16 hex characters, e.g. from caloogy-docs list)", 2)
    return m[1]


def get_doc(args, ref: str) -> dict:
    return api(args, "GET", f"/api/docs/{doc_id(ref)}")


WRITERS = ("owner", "manage", "edit")


def writable(d: dict) -> dict:
    """a document I may change: mine, or shared with me as an editor / manager"""
    if d.get("role") not in WRITERS:
        who = (d.get("ownerUser") or {}).get("name") or d.get("owner")
        raise Fail(f"“{title_of(d)}” is {who}'s and you can only view it. Ask them for edit access, or make your own copy: "
                   f"caloogy-docs read {d['id']} | caloogy-docs new \"…\" --file -", 1)
    return d


def mine(d: dict) -> dict:
    if d.get("role") != "owner":
        who = (d.get("ownerUser") or {}).get("name") or d.get("owner")
        raise Fail(f"“{title_of(d)}” belongs to {who} — only the owner can move it to the trash.", 1)
    return d


def read_text(args) -> str | None:
    """the new Markdown from --text or --file (- = stdin), or None if neither was given"""
    if getattr(args, "text", None) is not None and getattr(args, "file", None) is not None:
        raise Fail("Use either --text or --file, not both.", 2)
    if getattr(args, "text", None) is not None:
        return args.text
    if getattr(args, "file", None) is not None:
        if args.file == "-":
            return sys.stdin.read()
        try:
            return Path(args.file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise Fail(f"Can't read {args.file}: {e.strerror}", 2)
        except UnicodeDecodeError:
            raise Fail(f"{args.file} isn't UTF-8 text.", 2)
    return None


def put(args, d: dict, body: dict, rev: int | None) -> dict:
    """save; rev = the version the change was made against (409 if the document changed since)"""
    status, r = request(args, "PUT", f"/api/docs/{d['id']}", {**body, "rev": d["rev"] if rev is None else rev})
    if status == 409:
        now = (r.get("doc") or {}).get("rev")
        raise Fail(f"The document changed since revision {rev if rev is not None else d['rev']} (now {now}). "
                   "Read it again and redo the change.", 1)
    if status != 200:
        raise Fail(message(status, r))
    return r


def saved(args, d: dict, r: dict, what: str, **extra) -> None:
    emit(args, {"ok": True, "id": d["id"], "url": link(args, d["owner"], d["id"]), "rev": r["rev"], "updated": when(r["updated"]), **extra},
         f"{what} “{title_of(d)}” (rev {r['rev']})  {link(args, d['owner'], d['id'])}")


def replace_once(content: str, old: str, new: str, every: bool) -> tuple[str, int]:
    """exact text replacement; one match unless every=True (then all of them)"""
    if old == "":
        raise Fail("--old can't be empty.", 2)
    n = content.count(old)
    if n == 0:
        raise Fail("--old text not found in the document (it must match exactly, including spaces and line breaks). "
                   "Run caloogy-docs read to see the current text.", 1)
    if n > 1 and not every:
        raise Fail(f"--old text appears {n} times — add more surrounding text so it's unique, or pass --all.", 1)
    return content.replace(old, new), n


# ---------------------------------------------------------------- commands

def cmd_login(args) -> None:
    url = base_url(args)
    if args.device_code:
        device = {"device_code": args.device_code, "interval": 2, "expires_in": 600}
    else:
        name = args.name or f"caloogy-docs on {socket.gethostname().split('.')[0] or platform.node()}"
        status, device = request(args, "POST", "/api/cli/start", {"name": name}, auth=False)
        if status != 200:
            raise Fail(device.get("message") or f"Couldn't start a login (HTTP {status}).")
        if args.no_wait:
            emit(args, {"verify_url": device["verify_url"], "user_code": device["user_code"],
                        "device_code": device["device_code"], "expires_in": device["expires_in"],
                        "next": f"caloogy-docs login --device-code {device['device_code']}"},
                 f"Open this link, check the code and choose Allow:\n\n  {device['verify_url']}\n  code: {device['user_code']}\n\n"
                 f"Then run:\n  caloogy-docs login --device-code {device['device_code']}")
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
            raise Fail("The login link expired. Run caloogy-docs login again.")
        if status == 429:
            time.sleep(10)
        time.sleep(float(device.get("interval") or 2))
    raise Fail("Timed out waiting for approval. Run caloogy-docs login again.")


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


def cmd_list(args) -> None:
    q = (args.query or "").casefold()
    match = lambda d: not q or q in (d.get("title") or "").casefold()
    if args.trash:
        me = api(args, "GET", "/api/me")["id"]
        items = [{"id": d["id"], "title": d["title"], "url": link(args, me, d["id"]), "deleted": when(d["deleted"])}
                 for d in api(args, "GET", "/api/trash") if match(d)]
        emit(args, {"trash": items}, "\n".join(f"  {d['id']}  {title_of(d)}   (deleted {d['deleted'][:16].replace('T', ' ')})" for d in items)
             or "The trash is empty.")
        return
    me = api(args, "GET", "/api/me")["id"]
    own = [] if args.shared else [summary(args, d, me, "owner") for d in api(args, "GET", "/api/docs") if match(d)]
    shared = [] if args.mine else [summary(args, d) for d in api(args, "GET", "/api/shared") if match(d)]
    lines = []
    if not args.shared:
        lines.append("My documents" + ("" if own else ": none"))
        lines += [f"  {d['id']}  {title_of(d)}   ({d['updated'][:16].replace('T', ' ')})" for d in own]
    if not args.mine:
        lines.append("Shared with me" + ("" if shared else ": none"))
        lines += [f"  {d['id']}  {title_of(d)}   — {d.get('owner_name') or d['owner']}, {ROLE_TXT.get(d['role'], d['role'])}" for d in shared]
    emit(args, {"mine": own, "shared": shared}, "\n".join(lines))


def cmd_read(args) -> None:
    d = get_doc(args, args.doc)
    if args.json:
        emit(args, full(args, d))
        return
    if args.meta:
        owner = (d.get("ownerUser") or {}).get("name") or d["owner"]
        print(f"# {title_of(d)}\n<!-- id {d['id']} · rev {d['rev']} · owner {owner} · you {ROLE_TXT.get(d['role'], d['role'])} · "
              f"updated {when(d['updated'])} · {link(args, d['owner'], d['id'])} -->\n")
    sys.stdout.write(d.get("content") or "")
    if d.get("content") and not d["content"].endswith("\n"):
        sys.stdout.write("\n")


def cmd_new(args) -> None:
    content = read_text(args) or ""
    d = api(args, "POST", "/api/docs", {"title": args.title or "", "content": content})
    emit(args, {"ok": True, **summary(args, {**d, "role": "owner"})},
         f"Created “{title_of(d)}”  {link(args, d['owner'], d['id'])}\n  id {d['id']}")


def cmd_write(args) -> None:
    content = read_text(args)
    if content is None and args.title is None:
        raise Fail("Give the new text with --file (- for stdin) or --text, and/or a new --title.", 2)
    d = writable(get_doc(args, args.doc))
    body = {}
    if content is not None:
        body["content"] = content
    if args.title is not None:
        body["title"] = args.title
    r = put(args, d, body, args.rev)
    if args.title is not None:
        d["title"] = args.title
    saved(args, d, r, "Saved")


def cmd_append(args) -> None:
    text = read_text(args)
    if text is None:
        raise Fail("Give the text to add with --file (- for stdin) or --text.", 2)
    for attempt in (0, 1):                          # someone saved in between: read again and add once more
        d = writable(get_doc(args, args.doc))
        cur = d.get("content") or ""
        sep = "" if not cur or cur.endswith("\n\n") else "\n" if cur.endswith("\n") else "\n\n"   # one blank line between
        new = cur + sep + text + ("" if text.endswith("\n") else "\n")
        status, r = request(args, "PUT", f"/api/docs/{d['id']}", {"content": new, "rev": d["rev"]})
        if status == 200:
            return saved(args, d, r, "Added to")
        if status != 409 or attempt:
            raise Fail(message(status, r) if status != 409 else "The document keeps changing — try again.")


def cmd_edit(args) -> None:
    for attempt in (0, 1):
        d = writable(get_doc(args, args.doc))
        if args.rev is not None and d["rev"] != args.rev:
            raise Fail(f"The document changed since revision {args.rev} (now {d['rev']}). Read it again and redo the change.")
        new, n = replace_once(d.get("content") or "", args.old, args.new, args.all)
        status, r = request(args, "PUT", f"/api/docs/{d['id']}", {"content": new, "rev": d["rev"]})
        if status == 200:
            return saved(args, d, r, f"Replaced {n} {'match' if n == 1 else 'matches'} in", replaced=n)
        if status != 409 or args.rev is not None or attempt:
            raise Fail(message(status, r) if status != 409 else "The document keeps changing — try again.")


def cmd_rename(args) -> None:
    d = writable(get_doc(args, args.doc))
    r = put(args, d, {"title": args.title}, None)
    d["title"] = args.title
    saved(args, d, r, "Renamed to")


def cmd_delete(args) -> None:
    done = []
    for ref in args.docs:
        d = mine(get_doc(args, ref))
        api(args, "DELETE", f"/api/docs/{d['id']}")
        done.append({"id": d["id"], "title": d.get("title") or ""})
    emit(args, {"ok": True, "trashed": done},
         "\n".join(f"Moved “{title_of(d)}” to the trash ({d['id']})" for d in done) + "\nRestore with: caloogy-docs restore <id>")


def cmd_restore(args) -> None:
    did = doc_id(args.doc)
    status, r = request(args, "POST", f"/api/docs/{did}/restore")
    if status != 200:
        raise Fail("That document isn't in your trash (caloogy-docs list --trash)." if status == 404 else message(status, r))
    d = get_doc(args, did)
    emit(args, {"ok": True, "id": did, "url": link(args, d["owner"], did)}, f"Restored “{title_of(d)}”  {link(args, d['owner'], did)}")


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

    p = argparse.ArgumentParser(prog="caloogy-docs", description="Read and write your docs.caloogy.com documents.",
                                epilog="DOC is a document's 16-character id or its link. Documents are Markdown.")
    p.add_argument("--json", action="store_true", help="machine-readable output (for scripts and AI tools)")
    p.add_argument("--url", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"caloogy-docs {__version__}")
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

    def text_in(sp):
        sp.add_argument("--file", "-f", help="read the Markdown from this file (- = stdin)")
        sp.add_argument("--text", "-t", help="the Markdown itself")

    s = sub.add_parser("list", parents=[common], help="documents you can open: yours and the ones shared with you")
    s.add_argument("-q", "--query", help="only titles containing this")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--mine", action="store_true", help="only your own documents")
    g.add_argument("--shared", action="store_true", help="only documents shared with you")
    g.add_argument("--trash", action="store_true", help="your trash")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("read", parents=[common], help="print a document's Markdown")
    s.add_argument("doc", metavar="DOC")
    s.add_argument("--meta", action="store_true", help="start with the title and a comment line (id, rev, owner, your role)")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("new", parents=[common], help="create a document")
    s.add_argument("title", nargs="?", default="", metavar="TITLE")
    text_in(s)
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("write", parents=[common], help="replace a document's whole text (and/or its title)")
    s.add_argument("doc", metavar="DOC")
    text_in(s)
    s.add_argument("--title", help="new title")
    s.add_argument("--rev", type=int, help="only if the document is still at this revision (from read --json)")
    s.set_defaults(fn=cmd_write)

    s = sub.add_parser("append", parents=[common], help="add text at the end of a document")
    s.add_argument("doc", metavar="DOC")
    text_in(s)
    s.set_defaults(fn=cmd_append)

    s = sub.add_parser("edit", parents=[common], help="replace exact text inside a document")
    s.add_argument("doc", metavar="DOC")
    s.add_argument("--old", required=True, help="the exact text to replace (must appear once, unless --all)")
    s.add_argument("--new", required=True, help="what to put instead (empty = delete it)")
    s.add_argument("--all", action="store_true", help="replace every occurrence")
    s.add_argument("--rev", type=int, help="only if the document is still at this revision")
    s.set_defaults(fn=cmd_edit)

    s = sub.add_parser("rename", parents=[common], help="change a document's title")
    s.add_argument("doc", metavar="DOC")
    s.add_argument("title", metavar="TITLE")
    s.set_defaults(fn=cmd_rename)

    s = sub.add_parser("delete", parents=[common], help="move documents to the trash (restore brings them back)")
    s.add_argument("docs", nargs="+", metavar="DOC")
    s.set_defaults(fn=cmd_delete)
    s = sub.add_parser("restore", parents=[common], help="bring a document back from the trash")
    s.add_argument("doc", metavar="DOC")
    s.set_defaults(fn=cmd_restore)

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
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"caloogy-docs: {e}", file=sys.stderr)
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
