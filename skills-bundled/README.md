# Skills bundled

Credit register for skills this repository runs, recommends, or learned from.
Checked against each publisher's default branch on 2026-11-07.

Nothing in this folder is a skill. No third-party skill text is stored in this repository. The 27 skills under `plugins/dts2-harness/skills/` were written here. Where a skill is "used", the harness installs or calls the publisher's copy in the user's project. Where a skill was "used in part", the harness follows a pattern and the words are ours.

## License verdict

No publisher below uses a license this repository is breaking.

| How it is used | What the license requires | What this repo does |
|---|---|---|
| Pattern only (interview, critique rubric) | MIT and Apache-2.0 do not reserve ideas or a workflow. Attribution is required when you distribute their files. | Their files are not in this tree. Credit is in this folder and in both READMEs. |
| Called by name, or installed with `npx skills add` into the user's project | A copy that is redistributed must keep that project's copyright and license notice. | The copy lands in the user's project, not in `plugins/dts2-harness`. Do not drop their copyright notice if those files are committed here. |

This repository is MIT, copyright Dobeu Tech Solutions LLC. That grant does not replace MIT or Apache-2.0 on someone else's files.

Two things to leave out:

- `anthropics/skills` document skills (`docx`, `pdf`, `pptx`, `xlsx`) are not used. That repo's `THIRD_PARTY_NOTICES.md` includes GPL-3.0 FFmpeg for those document skills. Do not add them.
- `vercel-labs/agent-skills` is named only inside a test fixture. Its README says MIT, and the repository has no `LICENSE` file. It is not installed. Do not vendor it until a license file exists.

## Publishers

### Matt Pocock — companion skills, installed per project

- Repo: https://github.com/mattpocock/skills
- License: MIT. Copyright (c) 2026 Matt Pocock. https://github.com/mattpocock/skills/blob/main/LICENSE
- Use: not bundled. `skills-check.py` installs the skill into the project with `npx skills add` and `--copy`. The harness then runs the installed skill.

| Skill | When |
|---|---|
| `grill-me` | After the setup interview, before the first approval |
| `improve-codebase-architecture` | After the end state is signed off, and again before tests |
| `writing-for-agents` | After the amended end state is signed off |
| `pr` | When a pull request is opened or its body is rewritten |
| `diagnosing-bugs` | Fix round 2, and again at the five-round cap |
| `ask-matt` | When the user asks a question |
| `research` | When the question is still open after `ask-matt` |
| `loop-me` | At the start of `/dt:run`, before builders are dispatched |
| `setup-pre-commit` | Once per repo, before the first commit |
| `code-review` | First contact with a repo that has no `.harness/` |

`to-spec` is the upstream replacement for the retired `request-refactor-plan`. The harness names that history and does not ship the old skill.

### Warp — merge conflicts

- Repo: https://github.com/warpdotdev/common-skills
- License: MIT. Copyright (c) 2026 Denver Technologies, Inc. https://github.com/warpdotdev/common-skills/blob/main/LICENSE
- Skill: `resolve-merge-conflicts` at https://github.com/warpdotdev/common-skills/tree/main/.agents/skills/resolve-merge-conflicts
- Use: not bundled. Installed when a merge conflict appears. Matt Pocock's copy of this skill was removed upstream, so this is the source the harness names.

### Corey Haines — go to market

- Repo: https://github.com/coreyhaines31/marketingskills
- License: MIT. Copyright (c) 2025 Corey Haines. https://github.com/coreyhaines31/marketingskills/blob/main/LICENSE
- Use: not bundled. `/dt:gtm` installs the repo and runs the publisher's skills. It does not reimplement them. `.agents/product-marketing-context.md` is the context file the harness may create for that pack.

The harness still calls four names that are no longer in the repo. The license is unchanged. The live skill is the one to credit:

| Name the harness calls | Live skill |
|---|---|
| `product-marketing-context` | [`product-marketing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/product-marketing) |
| `page-cro` | [`cro`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/cro) |
| `launch-strategy` | [`launch`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/launch) |
| `analytics-tracking` | [`analytics`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/analytics) |

These names still match: [`competitor-profiling`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/competitor-profiling), [`seo-audit`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/seo-audit), [`copywriting`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/copywriting), [`copy-editing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/copy-editing).

### Paul Bakaus — design critique and polish

- Repo: https://github.com/pbakaus/impeccable
- License: Apache-2.0. https://github.com/pbakaus/impeccable/blob/main/LICENSE
- Use: not bundled. When the plugin is installed, `/dt:run` calls `/impeccable critique`, `polish`, `harden`, `clarify`, `optimize`, and setup may call `/impeccable init`. The reviewer's own critique section is a short original rubric (0–4 usability checks, two simulated users, preserve / fix / open questions). It follows the shape of Impeccable's review and does not contain Impeccable's text.

### Yeachan Heo — interview pattern

- Repo: https://github.com/Yeachan-Heo/oh-my-claudecode
- License: MIT. Copyright (c) 2025 Yeachan Heo. https://github.com/Yeachan-Heo/oh-my-claudecode/blob/main/LICENSE
- Use: pattern only. The setup interview follows the deep-interview structure. The questions and the files under `skills/setup/` were written here. An existing `.omc/specs/deep-interview-*.md` can be read as input. It is not copied into this repo.

### Anthropic — frontend design, recommended by slug

- Repo: https://github.com/anthropics/skills
- Skill: [`frontend-design`](https://github.com/anthropics/skills/tree/main/skills/frontend-design)
- License on that skill: Apache-2.0. https://github.com/anthropics/skills/blob/main/skills/frontend-design/LICENSE.txt
- The repository has no top-level license file. The grant for this skill is the `LICENSE.txt` beside it.
- Use: not bundled. `skill-suggest.py` recommends the slug `frontend-design` for a frontend repo. The install command is not pinned to this URL. No Anthropic skill text is in this tree.

### Jesse Vincent — test-driven development, recommended by slug

- Repo: https://github.com/obra/superpowers
- License: MIT. Copyright (c) 2025 Jesse Vincent. https://github.com/obra/superpowers/blob/main/LICENSE
- Skill: [`test-driven-development`](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)
- Use: not bundled. `skill-suggest.py` recommends the slug when a repo has no tests. Matt Pocock's pack has a different skill, `tdd`, which the harness does not name.

### Seth Hobson — database skills, recommended by slug

- Repo: https://github.com/wshobson/agents
- License: MIT. Copyright (c) 2024 Seth Hobson. https://github.com/wshobson/agents/blob/main/LICENSE
- Use: not bundled. `skill-suggest.py` recommends the three slugs for a database repo and does not pin this URL.

| Skill | Path |
|---|---|
| `postgresql-table-design` | https://github.com/wshobson/agents/tree/main/plugins/database-design/skills/postgresql-table-design |
| `sql-optimization-patterns` | https://github.com/wshobson/agents/tree/main/plugins/developer-essentials/skills/sql-optimization-patterns |
| `database-migration` | https://github.com/wshobson/agents/tree/main/plugins/framework-migration/skills/database-migration |

These are not the Supabase skills. `supabase/agent-skills` (MIT, Copyright (c) 2026 Supabase, https://github.com/supabase/agent-skills) appears only as an example source string in a test. The harness does not install it.

## Integration, not a bundled skill

Composio is installed by the user. The skill at `plugins/dts2-harness/skills/composio/SKILL.md` was written here and tells the user to add Composio's own plugin.

- Repo: https://github.com/ComposioHQ/composio
- License: MIT. https://github.com/ComposioHQ/composio/blob/main/LICENSE
- Plugin the skill names: https://github.com/ComposioHQ/composio-plugin-cc
