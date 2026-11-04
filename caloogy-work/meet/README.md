# caloogy-meet · caloogy-call

The command line for Caloogy Meet: **`caloogy-meet`** makes video meetings on [meet.caloogy.com](https://meet.caloogy.com),
**`caloogy-call`** makes voice calls on [call.caloogy.com](https://call.caloogy.com). Make a new room link, list your
upcoming and recent rooms, and see whether anyone is in a room right now. Made to be driven by Claude Code, Codex and
other terminal AI tools — every command has `--json`. Python 3.9+, no dependencies.

Guides: <https://guide.caloogy.com/cli/work/meet/> · <https://guide.caloogy.com/cli/work/call/>

## Install

One package, both commands:

```bash
uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/meet"
# or
pipx install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/meet"
```

## Log in

Each command logs in on its own (a video login can't make voice calls, and the other way round):

```bash
caloogy-meet login
caloogy-call login
```

It prints a link and a code and opens your browser. Check that the page shows the same code, and choose **Allow**. The
tokens are saved in `~/.config/caloogy/meet.json` and `call.json` (only you can read them). A token can **make** rooms
of its kind and **list** yours — nothing else: it can't join a call, hear or see anything, or read a room's chat or
transcript. See or revoke connected tools on meet.caloogy.com or call.caloogy.com under your avatar →
**Command-line access**; `caloogy-meet logout` / `caloogy-call logout` revokes this computer's token.

## Let your AI use it

```bash
caloogy-meet install-skill          # writes the skills to ~/.claude/skills and ~/.codex/skills
caloogy-call install-skill
```

Restart Claude Code / Codex, then talk normally:

- "Give me a video meeting link." · "Start a voice call now."
- "Call Bob" — with [`caloogy-chat`](../chat) it makes the link and sends it to Bob.
- "Set up a meeting with Bob on Friday at 3pm" — with [`caloogy-calendar`](../calendar) the link goes in the event.
- "Is Bob in the room yet?"

## Commands

```bash
caloogy-meet new                    # a new video meeting link;  --open opens it in the browser
caloogy-call new                    # a new voice call link
caloogy-meet list                   # upcoming (nobody joined yet) and recent;  --upcoming, --recent, -n 20
caloogy-meet show abc-defg-hjk      # the link, and how many are in it now (a link works too)
caloogy-call open abc-defg-hjk      # open it in the browser
```

How rooms work: two people per room, both signed in to Caloogy. A room belongs to you and the first other person who
joins it. Audio and video go straight between your browsers. Rooms nobody used for 30 days are deleted. You can make
up to 30 rooms an hour.

Exit codes: 0 ok · 1 failed · 2 bad arguments · 3 not logged in.

## Development

```bash
cd caloogy-work/meet
PYTHONPATH=src python3 -m unittest discover -s tests
CALOOGY_MEET_URL=http://meet.localhost:5095 PYTHONPATH=src python3 -m caloogy_meet meet whoami   # against a dev server
CALOOGY_CALL_URL=http://call.localhost:5095 PYTHONPATH=src python3 -m caloogy_meet call whoami
```
