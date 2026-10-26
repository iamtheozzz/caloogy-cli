---
name: caloogy-docs
description: Read and write the user's Caloogy Docs (docs.caloogy.com) with the caloogy-docs CLI — list the documents they can open (their own and ones shared with them), read any of them as Markdown, and create, edit, append to, rename, trash or restore their own documents. Use when the user mentions Caloogy Docs, docs.caloogy.com, a docs.caloogy.com link, or asks to save / write / update / read one of their cloud documents.
---

# caloogy-docs

`caloogy-docs` reads and writes the user's documents on docs.caloogy.com. A document is **Markdown** with a separate
**title**. It has a 16-character id (`3f9c0a1b2d4e5f60`) and a link `https://docs.caloogy.com/<owner id>/<doc id>`;
every command takes either. Each save bumps its revision (`rev`).

What the CLI may do (the server enforces it):

- **Read** every document the user can open: their own, ones shared with them (any role), and public ones by link.
- **Change only the user's own documents** (`role: "owner"`): new, write, append, edit, rename, delete (to the trash),
  restore. Documents shared with them are read-only here even if they can edit them on the website — say so, and
  offer to make an own copy (`read … | new "…" --file -`).
- It can't share, change who can see a document, or delete anything permanently. Point the user to the website
  (Share button, Trash page) for those.

Pass `--json` when you need ids, revisions or links; `read` without `--json` prints just the Markdown.

## First time

```bash
caloogy-docs whoami --json          # exit code 3 = not logged in
caloogy-docs login --no-wait --json # prints verify_url + user_code; show both to the user
caloogy-docs login --device-code <device_code from above> --json   # waits until they press Allow (≤10 min)
```

The user must open `verify_url` themselves, check the code and press **Allow**. Never try to approve it for them. If
the tool isn't installed: `uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/docs"`
(or the same with `pipx install`).

## From plain language

| The user says | Run |
|---|---|
| "what's in my Caloogy docs?" | `caloogy-docs list --json` |
| "find my notes about the launch" | `caloogy-docs list -q launch --json` (titles only), then `read` the likely ones |
| "summarise https://docs.caloogy.com/2583df90/3f9c…" | `caloogy-docs read <link>` |
| "save this as a doc called Plan" | `caloogy-docs new "Plan" --file - <<'EOF' … EOF` |
| "fix the typo 'teh' in Plan" | `caloogy-docs edit <id> --old "teh plan" --new "the plan" --json` |
| "add today's notes to my journal" | `caloogy-docs append <id> --file - <<'EOF' … EOF` |
| "rewrite the whole Plan doc" | `read --json` (note `rev`), then `write <id> --rev <rev> --file new.md` |
| "rename it to Q4 plan" | `caloogy-docs rename <id> "Q4 plan"` |
| "delete the old draft" | `caloogy-docs delete <id>` (goes to the trash; `restore <id>` undoes it) |

- Multi-line text: always pass it through `--file -` with a quoted heredoc (`<<'EOF'`) or a file, never `--text`
  with `\n`. The title is separate: don't start the content with `# Title` unless the user wants a heading.
- Prefer `edit` (exact, unique text → new text) for small changes and `append` for adding; they keep anything else
  that changed meanwhile. Use `write` only for whole rewrites, with `--rev` from the `read --json` you based it on —
  if it says the document changed, read again and redo the change instead of forcing it.
- `edit --old` must match the current text exactly (spaces, line breaks, Markdown marks). If it's not found or not
  unique, `read` again and widen the snippet; `--all` replaces every occurrence.
- Ask before deleting more than one document, or before replacing a long document's whole text.
- The website shows changes on reload. If the user has the document open and typing, their next save may say the
  document changed — tell them to reload before editing there.
- Shared documents are private to the people they're shared with: don't paste them elsewhere unless the user asks.

## JSON shapes

- `list --json` → `{"mine": [...], "shared": [...]}`; each `{id, title, url, owner, owner_name?, role, level, updated, rev}`.
  `role`: owner / manage / edit / view; `level`: 1 public, 2 anyone signed in, 3 people invited, 4 only the owner.
- `read --json` → the same plus `content`, `created`, `can_write` (true only for the user's own).
- `new` / `write` / `append` / `edit` / `rename` → `{ok, id, url, rev, updated}`.
- Errors: `{"error": "..."}` with exit code 1 (failed), 2 (bad arguments) or 3 (not logged in / token revoked → `login`).

## Commands

```
login [--no-wait | --device-code C] [--no-browser] [--name N]   logout   whoami
list   [-q TEXT] [--mine | --shared | --trash]
read   DOC [--meta]
new    [TITLE] [--file F|- | --text T]
write  DOC [--file F|- | --text T] [--title T] [--rev N]
append DOC (--file F|- | --text T)
edit   DOC --old TEXT --new TEXT [--all] [--rev N]
rename DOC TITLE
delete DOC [DOC ...]      restore DOC
install-skill [--claude | --codex | --dir PATH]
```
