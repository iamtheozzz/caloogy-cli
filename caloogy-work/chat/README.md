# caloogy-chat

The command line for [Caloogy Chat](https://work.caloogy.com): see your conversations and unread messages, read a
chat, send messages to friends and groups (with a call link, a Caloogy doc or a web link attached), mark chats as
read and delete your own messages. Made to be driven by Claude Code, Codex and other terminal AI tools — every command
has `--json`. Python 3.9+, no dependencies.

Guide: <https://guide.caloogy.com/cli/work/chat/>

## Install

```bash
uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/chat"
# or
pipx install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/chat"
```

## Log in

```bash
caloogy-chat login
```

It prints a link and a code and opens your browser. Check that the page shows the same code, and choose **Allow**. The
token is saved in `~/.config/caloogy/chat.json` (only you can read it). A login is **read-only**: it can read the
conversations you're in and see your friends and their busy times. `caloogy-chat login --write` also lets it **send**
messages (marked "Sent from the command line"), start a direct chat with a **friend**, mark chats as read and delete
**your own** messages. It can never start groups, add people, or send or accept friend requests. A token stops working
after 90 days without use, or if your account is disabled. `send --file <path>` asks you at the terminal first. See or revoke connected tools on
work.caloogy.com under your avatar → **Command-line access**; `caloogy-chat logout` revokes this computer's token.

## Let your AI use it

```bash
caloogy-chat install-skill          # writes the skill to ~/.claude/skills and ~/.codex/skills
```

Restart Claude Code / Codex, then talk normally:

- "Any new messages?" · "What did Bob say this morning?"
- "Tell Bob I'm running five minutes late."
- "Start a voice call with Bob and send him the link." (with [`caloogy-call`](../meet))
- "When is Alice free this week?"

## Commands

```bash
caloogy-chat list                         # conversations, unread first;  --unread, -q TEXT
caloogy-chat unread                       # every unread message;  --mark-read
caloogy-chat read Bob                     # the last 30 messages;  -n 100, --all, --mark-read
caloogy-chat send Bob "on my way"         # --file - reads stdin
caloogy-chat send Bob "join" --call https://call.caloogy.com/abc-defg-hjk
caloogy-chat send Team "the plan" --doc https://docs.caloogy.com/2583df90/3f9c0a1b2d4e5f60 --title "Q4 plan"
caloogy-chat mark-read Bob                # or --all
caloogy-chat delete Bob <message id>      # your own messages only (ids from read --json)
caloogy-chat friends
caloogy-chat busy Alice                   # busy times this week;  --from 2026-11-09 --days 5
caloogy-chat whois 2583df90
```

`CONV` is a conversation's 12-character id, a group's name, or a person (name or 8-character account id) for your
direct chat with them. Sending to a friend you haven't chatted with yet starts the chat.

Exit codes: 0 ok · 1 failed · 2 bad arguments · 3 not logged in.

## Development

```bash
cd caloogy-work/chat
PYTHONPATH=src python3 -m unittest discover -s tests
CALOOGY_CHAT_URL=http://localhost:5099 PYTHONPATH=src python3 -m caloogy_chat whoami   # against a dev server
```
