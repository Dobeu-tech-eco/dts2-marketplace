### Fixed

- `/dts2:ask-expert` panel: voters now vote on the blind labels they actually see (`VOTE Option B: AGREE`) and `ask_expert.py panel-tally --blind-key` turns them back into seats; a vote on a seat's own option is ignored and counted.
- `/dts2:ask-expert` panel: the recorded round entries now contain each seat's full plan and votes, so the council dossier carries the panel's real reasoning and not just a one-line summary.
