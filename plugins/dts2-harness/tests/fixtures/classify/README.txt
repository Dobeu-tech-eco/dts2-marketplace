Recorded CLI output for roster.py classify tests. Never hand-write these:
an error classifier is only as good as the real lines it was tested on.
Redactions: request ids -> REDACTED, session ids -> REDACTED, org/repo -> <org>/<repo>, home -> $HOME.

copilot-context-budget.txt  gh copilot reviewer:security run, routeready run 20261021-092904, exit 1.
                            The trailing "exit 1" line the lead appended is not CLI output and is omitted.
muse-402.txt                muse exec --model muse-spark-1.3 "...", last line, 2026-10-22 (exit code not captured).
muse-402-preamble.txt       the same CLI on the other model: two preamble lines, then the failure line.
muse-429.txt                T3 task summary from the same provider, 2026-10-22.
muse-ok-reply.txt           muse exec --model muse-spark-1.3 "Reply OK" from an empty folder, 2026-10-22:
                            last 8 stderr lines then stdout, exit 0. The failure path could not be
                            triggered, so muse's exit code on 402/429 is unrecorded.
