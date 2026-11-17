Ballot answers for tests/test_gate_seat_ballots.py. Each file is one seat's raw answer; the name is
<case>.<expected>.txt, where <expected> is approve, reject or none (no vote can be read). The test runs every *.txt here,
so a new case needs only a new file.

NOT recorded output (unlike tests/fixtures/classify): the original ballots that reproduced the two failures
(the grok-4.7 preamble before `VOTE:`, and the gemini seat that died silently after a headless shell-permission denial)
were not available when this was written. Files starting "reconstructed-" follow the failure as described, and files
starting "synthetic-" simulate the gemini shapes, because `agy` could not be run signed in. Replace them, or add the
original answer beside them (keep its first lines byte-exact, scrub any private repository path), when it is on hand.
