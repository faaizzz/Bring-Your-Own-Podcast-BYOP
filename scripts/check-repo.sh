#!/usr/bin/env bash
# Repository sanity checks: layout, licence, conventions file and secret hygiene.
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0
err() { echo "FAIL: $*" >&2; fail=1; }

for d in apps/api apps/web docker docs .github .github/ISSUE_TEMPLATE; do
  [ -d "$d" ] || err "missing directory $d"
done

for f in LICENSE README.md CLAUDE.md CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md .editorconfig .gitignore .gitattributes \
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

# Every variable in .env.example (set or commented out) must be explained in docs/configuration.md.
if [ -f .env.example ] && [ -f docs/configuration.md ]; then
  for v in $(sed -nE 's/^#? ?([A-Z][A-Z0-9_]+)=.*/\1/p' .env.example | sort -u); do
    grep -q "$v" docs/configuration.md || err "docs/configuration.md does not mention $v"
  done
elif [ -f .env.example ]; then
  err "missing docs/configuration.md"
fi

# Relative links in the Markdown documentation must point at files that exist.
python3 - <<'PY' || fail=1
import pathlib, re, sys
root = pathlib.Path(".")
bad = []
files = [root / "README.md", root / "CONTRIBUTING.md", root / "SECURITY.md", *sorted((root / "docs").glob("*.md"))]
for path in files:
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        file_part = target.split("#", 1)[0]
        if file_part and not (path.parent / file_part).exists():
            bad.append(f"{path}: broken link {target}")
for line in bad:
    print("FAIL:", line, file=sys.stderr)
sys.exit(1 if bad else 0)
PY

# The compose file must stay valid and define the core services.
if [ -f docker-compose.yml ] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  services=$(docker compose -f docker-compose.yml config --services 2>/dev/null || true)
  for s in postgres redis api worker beat web; do
    echo "$services" | grep -qx "$s" || err "docker-compose.yml is missing service $s"
  done
fi

# CI must run the three jobs on push and pull_request, with no self-hosted runners.
ci=.github/workflows/ci.yml
if [ -f "$ci" ]; then
  for j in api web compose; do
    grep -qE "^  ${j}:" "$ci" || err "$ci is missing job $j"
  done
  grep -qE "^  push:|^on:.*push" "$ci" || err "$ci must trigger on push"
  grep -qE "^  pull_request:" "$ci" || err "$ci must trigger on pull_request"
  ! grep -q "self-hosted" "$ci" || err "$ci must use GitHub-hosted runners only"
else
  err "missing $ci"
fi

exit "$fail"
