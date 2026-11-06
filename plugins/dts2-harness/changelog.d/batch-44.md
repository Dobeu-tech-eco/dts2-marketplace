### Changed

- Speed: the verifier and fixer agents run on Sonnet; fix rounds 1-3 stay on Sonnet and rounds 4-5 go to a fresh Opus worker (`delegate.fix_round_model`, `delegate.py --fix-round N`). The lead and the whole-branch review stay on Opus.
- Speed: `son_model` now defaults to `sonnet` (set `son_model: opus` for hard tasks). A resumed son keeps the model its lane started on (`start_model` in `status.json`).
- Speed: builder, verifier, reviewer, fixer, scout and auditor agents ask for a one-hour prompt cache (`experimental.cacheTtl: 1h`); scout, auditor and verifier skip CLAUDE.md (`omitClaudeMd`).
- CI: pip cache, a Python 3.12-only matrix on pull requests (full matrix on main and merge queue), and tests run in parallel with pytest-xdist. `python3 -m unittest discover -s tests` still works.
