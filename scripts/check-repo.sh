#!/usr/bin/env bash
# Repository sanity checks: layout, licence, conventions file and secret hygiene.
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0
err() { echo "FAIL: $*" >&2; fail=1; }

for d in apps/api apps/web docker docs .github .github/ISSUE_TEMPLATE; do
  [ -d "$d" ] || err "missing directory $d"
done

for f in LICENSE README.md CLAUDE.md CONTRIBUTING.md .editorconfig .gitignore .gitattributes \
  docs/IMPLEMENTATION_WORKFLOW.md .github/ISSUE_TEMPLATE/bug_report.md \
  .github/ISSUE_TEMPLATE/feature_request.md; do
  [ -f "$f" ] || err "missing file $f"
done

grep -q "^MIT License" LICENSE || err "LICENSE is not MIT"
grep -Eq "^Copyright \(c\) [0-9]{4} .+" LICENSE || err "LICENSE has no copyright holder"

lines=$(wc -l < CLAUDE.md)
[ "$lines" -le 150 ] || err "CLAUDE.md has $lines lines (max 150)"
for dir in "apps/api/byop/" "apps/web/src/"; do
  grep -q "$dir" CLAUDE.md || err "CLAUDE.md does not describe $dir"
done
grep -q "no PRs\|no PR" CLAUDE.md || err "CLAUDE.md must state the no-PR rule"

if git rev-parse --git-dir >/dev/null 2>&1; then
  tracked_env=$(git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$' || true)
  [ -z "$tracked_env" ] || err "env file(s) tracked: $tracked_env"
fi

grep -qE '^\.env$' .gitignore || err ".gitignore must ignore .env"

# .env.example must document every variable the stack understands.
if [ -f .env.example ]; then
  for v in BYOP_SECRET_KEY BYOP_ADMIN_EMAIL BYOP_ADMIN_PASSWORD DATABASE_URL REDIS_URL \
    PUBLIC_BASE_URL OPENROUTER_API_KEY OPENAI_API_KEY ELEVENLABS_API_KEY \
    LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST; do
    grep -qE "^${v}=" .env.example || err ".env.example is missing $v"
  done
fi

# The compose file must stay valid and define the core services.
if [ -f docker-compose.yml ] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  services=$(docker compose -f docker-compose.yml config --services 2>/dev/null || true)
  for s in postgres redis api worker beat web; do
    echo "$services" | grep -qx "$s" || err "docker-compose.yml is missing service $s"
  done
fi

exit "$fail"
