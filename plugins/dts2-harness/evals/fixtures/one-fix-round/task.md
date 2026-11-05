# One fix round
Spec: `src/clamp.py` clamps a value into a range. The first builder round leaves the test red, so the gate refuses
any vote and asks for a fix round; the second round is green and the panel approves.
