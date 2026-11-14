# claude-code-config-backup

What the sweep assumed: an org portfolio review, part 2, covering the 20 private repositories the part 1 reviewer could not see. The org has 53. The owner has not confirmed the portfolio goal.

What the code shows: A scheduled raw backup of an agent configuration folder. The job pushes to a second branch, which has 83 commits through 2026-11-13. The default branch stopped on 2026-07-25 with 13 commits, so the repo looks idle on its front page and is not. The gitleaks pass found two hits. One is a documentation placeholder. The other is a credentials-shaped string in the history of a settings file. Treat it as exposed to anyone with read access and rotate it. The backup branch also tracks six compressed skill archives, which were not opened. The backup also carries per-project memory notes.

Choice: the owner did not pick. No panel was seated, so this file records one reviewer's comparison.
