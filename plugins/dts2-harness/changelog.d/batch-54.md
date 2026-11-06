### Fixed

- Agent rules: `no_secrets` is now on by default for a non-subscription agent, so `DTS2_SON_ENV_PASS` can no longer pass `GH_TOKEN` or other keys into it unless its rules say `no_secrets: false`.
- Agent rules: new `agent_rules.forced_auth(profile, declared)` returns `api-key` for any profile with `keyRequired`, so a roster line saying `auth: subscription` for a key agent (claude-api, codex-api, grok-api) cannot drop its restricted defaults.
- SDK: `dts2-run.py` second opinion no longer pulls the `<backend>-api` key into the subscription `codex` or `grok` CLI (which silently switched it to API billing). A provider key is injected only when the backend itself is an explicit `codex-api` / `grok-api` profile, and profiles load from the bundled and user layers only, never the working directory's project layer.
