### Changed

- Env: one scrubbed child-environment builder (`son_launch.scrub_env`) now serves every son, council seat, second opinion and `roster.py command` env. A subscription agent (the default; roster `auth` absent or `subscription`) never receives `*_API_KEY`, `ANTHROPIC_*`, `CODEX_*`, `XAI_*`, `OPENAI_*`, `AWS_*`, `GOOGLE_APPLICATION_CREDENTIALS` or the `CLAUDE_CODE_USE_*` provider switches, so a stray key in the parent shell can no longer bill the API account instead of the Max login. `CLAUDE_CODE_OAUTH_TOKEN` is kept for Claude subscription agents only.
- Env: an `auth: api-key` agent receives only its own key variable (the profile's `apiKeyEnv`). `DTS2_SON_ENV_PASS` still hands a named variable to a child on purpose.
- Codex: the profile's `apiKeyEnv` is now `CODEX_API_KEY` (what `codex exec` reads); `OPENAI_API_KEY` is no longer detected for codex.

### Added

- `son_launch.secret_shaped(text)` flags key-shaped strings for receipt and state writers, and `tests/test_secret_scan.py` fails when a key-shaped string ships in templates, profiles, skills, agents or docs.
