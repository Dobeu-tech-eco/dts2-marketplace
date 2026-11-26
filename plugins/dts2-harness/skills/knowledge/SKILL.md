---
name: knowledge
description: Keep your own standing preferences, glossary terms (brands, product lines, repo groups) and cross-project learnings in a private store that follows you across devices. Use for remember this preference, what is my standard setup, look up a term, or sync my knowledge.
disable-model-invocation: true
---

> Directory edition: do not run bundled scripts or hooks, a package launcher, or a download piped into a shell. Do not read tokens or credential files from the machine. Carry out the step with Read, Edit, Grep, Glob, and git or gh, and write the files the step names.

# Knowledge — your personal preferences and glossary, on every device

A small private store of things that are true for you, not for one repo: standing defaults ("my standard team is 6 agents"), glossary terms (a brand or product line and the repos in it) and lessons that apply everywhere. It is personal and private, and it is never part of the plugin. One Markdown file per entry lives under `entries/<kind>/<key>.md`; the store is a folder (`DTS2_KNOWLEDGE`, else `$DTS2_HOME/knowledge`, else `~/.dts2/knowledge`) that is usually a private git repo you own, so it can sync between devices.

All commands: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/knowledge.py" <command>`.

## Guided setup and join
Run this when the user types `/dt:knowledge setup` or `/dt:knowledge join`, or says "set up my knowledge store" or "connect this computer to my knowledge". Ask one question at a time and wait for each answer.
1. **Q1: Do you already have a knowledge store, or is this your first?** Existing → `join` (a new device, once per machine). New → `setup` (once per person).
2. **Q2: Where should it live?**
   - Cloud or local? Local only on this machine means no sync (`setup` only). Cloud has three choices:
   - (a) A private GitHub repo: free, the default. Signs in through `gh auth login` or your normal git sign-in. The user creates the empty private repo and gives its URL (`--remote`).
   - (b) A Cloudflare Worker + D1: also reachable from claude.ai web and phone. The user deploys `templates/knowledge-cloudflare/` with wrangler (see its README), sets the Worker secret `the knowledge token`, and exports the same value as `DTS2_the knowledge token` on this device. Ask for the Worker URL (`--url`). Never ask the user to paste the token into the chat and never write it anywhere. The claude.ai custom connector form may need OAuth, which the template does not provide yet (see its README); Claude Code can send the token as a header.
   - (c) A folder synced by OneDrive, Google Drive or Dropbox: cloud through the drive app. Ask for the folder path (`--path`).
3. **Q3 (new store only): What owner label should it carry?** A short name such as `acme-owner`.
4. **Run it.**
   - New: `setup --owner <label> --backend git|folder|local|cloudflare [--remote <url>] [--path <dir>] [--url <worker url>]`. Add `--force` only if the user confirms replacing an existing store.
   - Existing: `join --backend git|folder|cloudflare [--remote <url>] [--path <dir>] [--url <worker url>]`. It reads the owner from the store and prints "this device is now tied to <owner>'s knowledge store".
5. Confirm in one line: owner, backend and where it lives. This device's choice is kept in `~/.dts2/knowledge.json`.
Never ask for or store an API key or password; sign-in comes from `gh`/git or the drive app. For Cloudflare the token is read from `DTS2_the knowledge token` only; if it is unset, setup and join still work and print a note, and `sync` exits 2 until it is set. `init [--remote <url>]` still works as an alias of `setup --backend git`.

## Kinds and keys
- `preference` (default): a standing default, such as `agents.standard`.
- `term`: a glossary entry with `--alias` names and `--tag` words, such as a brand and its repos.
- `learning`: a lesson that applies across projects.
- Keys are lowercase: letters, digits, `.`, `_`, `-`, up to 64 characters, starting with a letter or digit.

## Steps: map what the user says to a command
1. **set** ("remember that...", "my standard is...") `set <key> "<value>" [--kind preference|term|learning] [--alias <name>]... [--tag <word>]...`
2. **get** ("what is my...", "what does X mean") `get <key or alias>`; add `--json` to parse it. Exit 3 means nothing matches: say so.
3. **find** ("anything about...") `find <text>` searches keys, aliases, tags and values; `--kind` narrows it.
4. **list** ("show everything I saved") `list [--kind <kind>]`.
5. **rm** ("forget...") `rm <key>`.
6. **sync** ("sync my knowledge", or after any `set` or `rm`) `sync`. Run it right after `set` and `rm` whenever a remote or Worker URL exists (`status` shows it). With the Cloudflare backend it pulls newer remote entries and pushes newer local ones. With no remote it only commits locally and says so.
7. **status** ("is it set up?") `status` shows the store path, counts per kind, the remote and whether there are unsynced changes.
8. **Confirm** in one line: what was stored or found, under which key, and whether it was synced.

## Examples
A preference:
```
set agents.standard "6 agents"
```
A glossary term for a brand with several repos (generic name):
```
set acme "Acme product line: the acme-web, acme-api and acme-docs repos ship together" --kind term --alias "Acme Co" --alias "acme-*" --tag acme-web --tag acme-api --tag acme-docs
get "Acme Co"
```
`get` finds the term by its key or by any alias, ignoring case. `/dt:setup` uses the tags and aliases to spot that the repo it is in belongs to `acme`.

## Rules
- Never store secrets: no tokens, passwords, API keys, private keys or credentials. The script refuses them (exit 2). Do not work around a refusal; tell the user the store is for preferences and glossary only.
- Read the store only when the user invokes this skill or `/dt:setup` does. No hook and no other skill reads it.
- Keep values short and plain; the value is the text after the front matter.
- A sync conflict on the same key keeps the newer `updated` entry and saves the other as `<key>.conflict-<time>.md` beside it. Tell the user so they can review it.
- This is separate from cooldowns (`/dt:cooldown`): those are live per-account state and are not synced through git.
