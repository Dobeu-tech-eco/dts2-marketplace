### Fixed

- `ask_expert.py backup` and `delete` check the backup bundle from any folder (not only inside a git repo), and a relative `--dest` now lands where you typed it instead of inside the temporary mirror.
- `/dts2:ask-expert` panel: new `ask_expert.py panel-tally` counts the three plans (keep, fold, template, archive, delete) and the cross-review votes (several `AGREE` or `DISAGREE` lines per seat). The panel no longer goes through the five-seat council tally or the approve/reject ballot dispatcher, which dropped those verdicts.
