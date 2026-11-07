# API agents: claude-api, codex-api, grok-api

Setup and limits for the three built-in agent profiles that run a vendor CLI on a pay-as-you-go API key, billed apart from your subscriptions. It is for anyone who wants extra reviewers, second opinions or overflow builders when the Max agents are rate limited. These profiles never lead a run and never sign off.

Contents: what the harness guarantees, then four steps: create a capped key, store it, add it to the roster, widen the rules (optional).

| Agent | Command | Key variable | Roles | Own home |
|---|---|---|---|---|
| `claude-api` | `claude -p --model sonnet --output-format json --max-budget-usd N` | `ANTHROPIC_API_KEY` | reviewer, overflow builder | `CLAUDE_CONFIG_DIR` |
| `codex-api` | `codex exec -m gpt-6.1-sol --sandbox read-only --json` | `CODEX_API_KEY` | second opinion, reviewer (read-only) | `CODEX_HOME` (`config.toml` with `forced_login_method = "api"`) |
| `grok-api` | `grok -p -m grok-build-0.1` (plan mode, no Bash/Edit/Write) | `XAI_API_KEY` | reviewer, security-review fallback | none |

The existing `grok` and `codex` profiles stay on their subscriptions. `claude-api` is never started with `--bare`, which would turn off plugins, agents and skills.

## What the harness guarantees

- Max agents and sons run with every `*_API_KEY`, `ANTHROPIC_*`, `CODEX_*`, `XAI_*`, `OPENAI_*` and `CLAUDE_CODE_USE_*` variable removed.
- An API agent's key is put in that one child's environment at launch (`roster.py exec`, which `roster.py command --prompt-file` prints as the line to run). It is never written to a file, the repo, a receipt, a ledger or memory, and never printed.
- Each agent's private home is `~/.dts2/agents-home/<name>` (mode 0700), so `claude-api` cannot see the Max login and `codex-api` cannot fall back to a ChatGPT login.
- Defaults for a non-subscription agent apply: read-only, review/docs/research only, `standard` tier at most, $0.50 a run and $5 a day, and deploy/merge/release/secrets/delete always denied.
- No key, no launch: dispatch skips the agent with the reason, `roster.py exec` exits 2 naming the ref or variable, and `doctor.py` shows `missing`.
- Receipts and the spend ledger record `credential: <keyring | op | doppler | env:NAME>`, never the value.

## 1. Create an isolated, capped key

- Anthropic: in the Console create a workspace just for the harness, set a monthly spend limit on it, and create an API key inside that workspace.
- OpenAI: create a separate project, set its budget, and create a project API key.
- xAI: create a dedicated API key in the xAI console with a spend cap.

## 2. Store the key

Pick one; the key never goes in the repo or in `.harness/config.yaml`.

- System keyring: `python3 -c "import keyring,getpass; keyring.set_password('dts2','claude-api',getpass.getpass())"`, or `secret-tool store --label dts2 service dts2 username claude-api` (Linux), `security add-generic-password -s dts2 -a claude-api -w` (macOS). Ref: `keyring:dts2/claude-api`.
- 1Password: ref `op://Vault/Item/field` (read with `op read`).
- Doppler: ref `doppler:PROJECT/CONFIG/NAME` (read with `doppler secrets get NAME --plain`).
- Environment: export `ANTHROPIC_API_KEY`, `CODEX_API_KEY` or `XAI_API_KEY` in the shell that starts the harness (or `env:NAME` to read another variable). Only the API agent receives it.

Then point the profile at it with a user profile (this layer merges over the built-in one):

```json
{ "name": "claude-api", "apiKeyRef": "keyring:dts2/claude-api" }
```

saved as `~/.dts2/agents/claude-api.json`. For tests, `DTS2_OP_BIN`, `DTS2_DOPPLER_BIN`, `DTS2_SECRET_TOOL_BIN` and `DTS2_SECURITY_BIN` point at other binaries.

## 3. Add it to the roster

```yaml
roster:
  - name: claude
  - name: claude-api
  - name: codex-api
  - name: grok-api
```

`auth: api-key` is the profile default. Check with `python3 scripts/doctor.py` (`api-key claude-api  set (keyring)`) and `python3 scripts/roster.py list`.

## 4. Widen the rules (optional)

```
python3 scripts/roster.py rules claude-api --set allow_tasks=review,docs,research,build --set read_only=false
```

This is the only way `claude-api` becomes an overflow builder. Keep a spend cap on the provider side as well: `codex` and `grok` have no per-run budget flag, so for them the provider cap is the hard limit and the harness daily cap is checked from the spend ledger.
