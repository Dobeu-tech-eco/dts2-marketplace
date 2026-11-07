# Privacy

**dt** and this repository are a product of **Dobeu Tech Solutions LLC**, New York, NY.

The controlling privacy policy is the live page:

https://dobeu.net/privacy

Last updated there: October 27, 2026. That page is the company policy for dobeu.net, the Dobeu client portal, and related company services. If this file and that page ever differ, the live page wins for those services.

## This product

The `dt` plugin does not send your prompts, repository contents, or usage to Dobeu Tech Solutions LLC. It does not include a Dobeu analytics tag, cookie, or account.

What it writes stays on your machine and in the repositories you point it at:

- Per-repo notes under `.harness/` and settings in `.claude/dts2-harness.local.md`
- Approvals you write in `.claude/settings.local.json`
- Machine-wide state under `~/.dts2/` (fleet notes, cooldowns, a Composio tool map, and an optional knowledge store)

Optional pieces talk only to services you choose:

- GitHub, through the `gh` and `git` logins already on your machine
- Composio, only if you install and sign in to Composio yourself
- A Cloudflare Worker you deploy yourself for `/dt:knowledge`, using a token you set as `DTS2_KNOWLEDGE_TOKEN`

Model calls go to the agent provider you are already signed in to (Claude Code, or another CLI you configured). Dobeu does not receive those calls.

## Your rights

To exercise a privacy right with Dobeu Tech Solutions LLC, email jeremyw@dobeu.net with the subject “Data Request — [your right]”. The live privacy policy states the rights, the 30-day response, and the California terms.

Related live pages:

- [Cookie Policy](https://dobeu.net/cookies)
- [Marketing opt-out](https://dobeu.net/marketing-opt-out)
- [SMS opt-in](https://dobeu.net/optin/sms)
- [Terms of Service](https://dobeu.net/terms)

Dobeu Tech Solutions LLC · New York, NY · jeremyw@dobeu.net · (848) 318-7664
