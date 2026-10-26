# caloogy-cli

Command-line tools for [Caloogy](https://caloogy.com) — for you, and for the AI tools you run in a terminal
(Claude Code, Codex, …). Each tool signs in with your Caloogy account and only ever touches your own data.

| Product | Tool | Folder |
|---|---|---|
| Caloogy Work · Calendar ([calendar.caloogy.com](https://calendar.caloogy.com)) | `caloogy-calendar` | [`caloogy-work/calendar`](caloogy-work/calendar) |
| Caloogy Work · Docs ([docs.caloogy.com](https://docs.caloogy.com)) | `caloogy-docs` | [`caloogy-work/docs`](caloogy-work/docs) |

More Caloogy products will get their own folder here.

## Quick start (calendar)

```bash
uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/calendar"
#   or: pipx install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/calendar"
caloogy-calendar login           # approve in the browser
caloogy-calendar install-skill   # teach Claude Code / Codex how to use it
```

Then just tell your AI: *"add dentist tomorrow 3 to 4pm to my Caloogy calendar"*, or *"sync my Feishu calendar for
the next month into Caloogy"*.

## Quick start (docs)

```bash
uv tool install "git+https://github.com/iamtheozzz/caloogy-cli#subdirectory=caloogy-work/docs"
caloogy-docs login
caloogy-docs install-skill
```

Then: *"save this as a Caloogy doc called Q4 plan"*, *"what's in my Caloogy docs?"*, *"fix the date in Q4 plan"*.

Guides for every tool: <https://guide.caloogy.com>

## License

[MIT](LICENSE)
