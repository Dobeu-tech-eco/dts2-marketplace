Ballot answers for tests/test_gate_seat_ballots.py. Each file is one seat's raw answer; the name is
<case>.<expected>.txt, where <expected> is approve, reject or none (no vote can be read). The test runs every *.txt here,
so a new case needs only a new file.

NOT recorded output (unlike tests/fixtures/classify): the original ballots that reproduced the two failures
(the grok-4.7 preamble before `VOTE:`, and the gemini seat that died silently after a headless shell-permission denial)
were not available when this was written. Files starting "reconstructed-" follow the failure as described, and files
starting "synthetic-" simulate the gemini shapes, because `agy` could not be run signed in. Replace them, or add the
original answer beside them (keep its first lines byte-exact, scrub any private repository path), when it is on hand.

lane-d30/ holds the rest of a reconstructed panel round for tests/test_gate_replay_d30.py: ballot-prompt.txt (the ballot file
handed to each seat; placeholder content in the structure phase-1-gate.md asks for), claude.txt and codex.txt (strict answers
from the seat that votes beside the two failing seats and the seat that replaces a failed one). The failing answers themselves
are the grok-preamble and synthetic-gemini files in this folder. Everything in lane-d30/ is reconstructed, not recorded.
