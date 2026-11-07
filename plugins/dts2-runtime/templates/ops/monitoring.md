# Monitoring: <project>

Fill each table. A row left as a placeholder means the check does not exist yet.

## Error tracking

| field | value |
|---|---|
| tool | <hosted error tracker, or the hosting provider's own error view> |
| project | <name> |
| where the DSN or key lives | <secret name only, never the value> |
| environments reported | production, staging |
| release tagging | each deploy sends its version so an error maps to a release |
| triage owner | <who reads new errors> |

Setup steps: add the SDK, read the key from the environment, send the release version, deploy to staging and throw one test error to confirm it arrives.

## Uptime check

| field | value |
|---|---|
| tool | <uptime service or provider health check> |
| url | <one key route, not only the home page> |
| interval | 1 to 5 minutes |
| expected | status 200 and a text marker that proves the page rendered |
| regions | at least two |

Keep one check at first. Add more only when a past incident would have been caught by it.

## Alert route

| severity | trigger | goes to | how |
|---|---|---|---|
| page | uptime check fails twice in a row | <on-call person> | <phone or pager channel> |
| notify | error rate above <n> per minute for 5 minutes | <team channel> | <chat message> |
| ticket | new error type seen in production | action items | `action-items.py <repo> add Deploy "<error>"` |

Test the route once a quarter: trigger a harmless alert and confirm a human saw it.
