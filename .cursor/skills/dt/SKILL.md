---
name: dt
description: "Run a DT harness command in Cursor. Use when the user invokes /dt or names a /dt-<command> procedure. Setup scaffolds only after an end-state approval. Run stops at the plan and ship gates."
disable-model-invocation: true
---

# dt

DT: Init to Ship Auto Agent Orchestrator. Dobeu Tech Solutions LLC. MIT.

Invoke the matching skill. Each one is a procedure, not an index entry.

- `/dt-action-items`
- `/dt-ask-expert`
- `/dt-autopilot`
- `/dt-check-in`
- `/dt-composio`
- `/dt-cooldown`
- `/dt-dpp`
- `/dt-dpp-full`
- `/dt-evolve`
- `/dt-feature`
- `/dt-find-skills`
- `/dt-fleet`
- `/dt-fullauto`
- `/dt-gtm`
- `/dt-incidents`
- `/dt-knowledge`
- `/dt-learn`
- `/dt-machine-prep`
- `/dt-model`
- `/dt-onboard`
- `/dt-pr-sweep`
- `/dt-repo-sweep`
- `/dt-run`
- `/dt-sdk`
- `/dt-setup`
- `/dt-ship`
- `/dt-steer`

Start with `/dt-setup` when `.harness/end-state.md` is missing. `/dt-check-in` only reads. `/dt-run` plans and builds only after `dt_gate.py` accepts the approvals. Merges, fleet broadcast, hook install, the headless SDK, and paid provider calls stay unexecuted.
