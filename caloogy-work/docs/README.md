# caloogy-docs

The command line for [docs.caloogy.com](https://docs.caloogy.com): list the documents you can open, read them as
Markdown, and create, edit, rename, trash and restore your own. Made to be driven by Claude Code, Codex and other
terminal AI tools — every command has `--json`. Python 3.9+, no dependencies.

Guide: <https://guide.caloogy.com/cli/work/docs/>

## Install

```bash
uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/docs"
# or
pipx install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/docs"
```

## Log in

```bash
caloogy-docs login
```

It prints a link and a code and opens your browser. Check that the page shows the same code, and choose **Allow**. The
token is saved in `~/.config/caloogy/docs.json` (only you can read it). It can **read** every document you can open
(yours, ones shared with you, public ones) and **change only your own** documents — never other people's, never who a
document is shared with, and it can't delete anything for good (deleting moves to the trash). See or revoke connected
tools on docs.caloogy.com under your avatar → **Command-line access**; `caloogy-docs logout` revokes this computer's
token.

## Let your AI use it

```bash
caloogy-docs install-skill          # writes the skill to ~/.claude/skills and ~/.codex/skills
```

Restart Claude Code / Codex, then talk normally:

- "What's in my Caloogy docs?" · "Summarise https://docs.caloogy.com/2583df90/3f9c0a1b2d4e5f60"
- "Save this plan as a Caloogy doc called *Q4 plan*."
- "In Q4 plan, change the launch date to Nov 20." · "Add today's notes to my Journal doc."
- "Move the old draft to the trash."

## Commands

```bash
caloogy-docs list                                   # yours + shared with you;  -q TEXT, --mine, --shared, --trash
caloogy-docs read 3f9c0a1b2d4e5f60                  # the Markdown (a link works too);  --meta, --json
caloogy-docs new "Q4 plan" --file plan.md           # --file - reads stdin;  --text "…"
caloogy-docs edit 3f9c0a1b2d4e5f60 --old "Nov 13" --new "Nov 20"    # exact text, must be unique (or --all)
caloogy-docs append 3f9c0a1b2d4e5f60 --text "- call the printer"
caloogy-docs write 3f9c0a1b2d4e5f60 --file plan.md --rev 7          # replace everything (only if still at rev 7)
caloogy-docs rename 3f9c0a1b2d4e5f60 "Q4 plan (final)"
caloogy-docs delete 3f9c0a1b2d4e5f60                # to the trash;  restore brings it back
caloogy-docs restore 3f9c0a1b2d4e5f60
```

How documents work:

- A document is Markdown plus a separate title, with a 16-character id and a link
  `https://docs.caloogy.com/<owner id>/<doc id>`. Every command takes the id or the link.
- Every save bumps the revision (`rev`). `edit` and `append` re-read and apply on top of the latest version, so they
  never wipe someone else's change; `write --rev N` refuses if the document moved on since you read revision N.
- Documents shared with you are read-only here, whatever your role on the website. Copy one into your own with
  `caloogy-docs read <id> | caloogy-docs new "My copy" --file -`.
- Changes show up on docs.caloogy.com on reload.

Exit codes: 0 ok · 1 failed · 2 bad arguments · 3 not logged in.

## Development

```bash
cd caloogy-work/docs
PYTHONPATH=src python3 -m unittest discover -s tests
CALOOGY_DOCS_URL=http://localhost:5097 PYTHONPATH=src python3 -m caloogy_docs whoami   # against a dev server
```
