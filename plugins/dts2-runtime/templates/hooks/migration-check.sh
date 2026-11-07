#!/usr/bin/env bash
# dts2 optional hook: Stop. Reminds you to generate and review migrations when schema files changed.
# Non-blocking: prints a systemMessage only. Never runs migrations.
set -uo pipefail

command -v python3 >/dev/null 2>&1 || exit 0
command -v git >/dev/null 2>&1 || exit 0
input="$(cat)"
active="$(printf '%s' "$input" | python3 -I -c 'import json,sys
try:
    print("yes" if json.load(sys.stdin).get("stop_hook_active") is True else "no")
except Exception:
    print("no")' 2>/dev/null)"
[ "$active" = "yes" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
changed="$(git status --porcelain 2>/dev/null)" || exit 0
[ -n "$changed" ] || exit 0

printf '%s\n' "$changed" | python3 -I -c 'import json,re,sys
pattern = re.compile(r"(^|/)(prisma/schema\.prisma|prisma/migrations|supabase/migrations|drizzle|migrations|db/migrate)(/|$)")
hits = []
for line in sys.stdin.read().splitlines():
    path = line[3:].split(" -> ")[-1].strip().strip(chr(34))
    if pattern.search(path):
        hits.append(path)
if hits:
    shown = ", ".join(hits[:5]) + (" and more" if len(hits) > 5 else "")
    msg = ("Database schema or migration files changed (" + shown + "). Generate and review a migration before "
           "shipping, for example npx prisma migrate dev --create-only, supabase db diff, or drizzle-kit generate. "
           "Nothing was run for you.")
    print(json.dumps({"systemMessage": msg}))' 2>/dev/null
exit 0
