### Changed
- dpp, autopilot and fullauto call the lanes.py lifecycle commands (`transition`, `shutdown`, `reconcile`, `run-record`, `builder`, `run-resume`, `fold-done`, `merge-resume`, `walkthrough-failed`, `report`) where they move a phase, resume, create or merge a PR, end a run or report; a test checks every `lanes.py <sub>` a skill names is real.
