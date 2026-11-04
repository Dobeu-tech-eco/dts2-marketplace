# Credential handoff: <project>

Agents never hold standing production credentials. When a task needs production access (take a backup, run the post-deploy watch, read logs), a person issues a scoped, short-lived credential for that one task and revokes it afterwards.

## What may be issued

| task | scope | lifetime | issued by |
|---|---|---|---|
| backup before a migration | read-only on the data store, plus write to the backup location only | 1 hour | <owner> |
| post-deploy watch | read-only on logs, metrics and the error tracker | watch window plus 10 minutes | <owner> |
| restore test | write to the scratch target only | 1 hour | <owner> |

Never issued to an agent: write access to production data, deploy keys, billing, user management, or anything with no expiry.

## Handoff steps

1. The agent records what it needs as an action item in the Secrets group: the name, what it unlocks, and the scope and lifetime above. It never writes the value anywhere.
2. The person creates the credential in the provider with that scope and expiry and puts it in the agent's environment for this session only (not in a file in the repo).
3. The agent uses it for the named task and stops. It does not copy it, log it or pass it to a subagent.
4. The person revokes it (or lets it expire) and marks the action item done.

## If a task cannot be done with a scoped credential

Park it. Add an action item that says what a person must run, with the exact command, and move on.
