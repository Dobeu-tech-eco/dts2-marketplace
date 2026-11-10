# Chairman resolution

The Chairman/head/tiebreaker seat is `latest-frontier-claude`, never a version pin.
This is separate from the panel's Claude frontier tier. The profile's
`councilModels.headClass` names this class; no project setting may turn it into
a fixed model or a restricted-access default.

At each run, obtain the authenticated runtime's live model catalog and identify
the latest generally available frontier Claude, ranked by capability and release.
Supply those catalog rows to `scripts/chairman.py --catalog <catalog.json>
--record .harness/runs/<stamp>/chairman-resolution.json`. Rows explicitly carry
`id`, `provider: claude`, `available`, `restricted`, `frontier`, and numeric `rank`.
An unknown availability or restriction status is not eligible. The runtime lookup
is the caller's responsibility; the resolver never pretends a bundled model list
is live. Dispatch the returned exact `model`, rather than the class string.

If frontier lookup fails, obtain the best available Claude from the runtime,
mark those rows non-frontier and resolve again. If a dispatch is unavailable,
mark that model unavailable and retry resolution. Record each attempt and the
actual model reported by the successful runtime response in the run record and
council decision. A selected model is not proof it was used. If no Claude is
available, park; never manufacture a vote or silently switch providers.

Mythos 5.2 is restricted to vetted organizations. Restricted models, including
all Mythos models, are excluded from this general seat even if the current
organization happens to have access. They are never an automatic default.

Reserve the resolved Chairman model from both the panel and council voter seats,
including replacements. Keep three frontier panel voters, the existing tiebreak
rules, five council voters, mandatory dissent briefs, and all hard stops. A red
check is never voted on. Approvals remain HEAD-pinned and human-default in
`dts2_approvals`, unwritable by sons; merge only under the standing `merge_policy`.

Council seat allocation requires --chairman-record pointing at this resolution; it excludes the exact id, runtime aliases and bare family aliases from seats and bench. Panel overlap means park.

## Live catalog acquisition and ranking

For an API-authenticated runtime, use its existing authenticated Anthropic SDK
client: `list(client.models.list())` (GET /v1/models, paginate through the SDK).
No key is requested, copied or written by this workflow. Preserve that raw
response as catalog evidence. Cross-check its available model ids against
Anthropic's current release announcement and model overview. Mark restricted
access explicitly (false only when generally available); mark frontier only
for the newest generally available top-capability Claude family. Rank capability
first, then release date, and assign monotonically increasing numeric ranks.
Preserve aliases from the runtime in each normalized row. Record the source URLs,
catalog retrieval time and ranking rationale with the input JSON. If the runtime
reports only names, do not invent access or capability metadata.

A subscription-only Claude Code runtime may not expose the Models API: use its
authenticated model picker/catalog if available with the same evidence rules.
If neither catalog is accessible, frontier resolution has failed. Use an
explicitly available Claude from the runtime picker as fallback, record why and
its exact response identity; if availability cannot be established, park.
The resolver is deterministic over this evidenced normalized catalog; it does
not claim to discover live models by itself.
